"""
Tests for ITEM-ART-001: Enhanced Audit Trail Signing.

Tests cover:
- HMAC signing backend
- RSA signing backend
- Ed25519 signing backend
- KMS signing backend (mocked)
- Signature verification
- Key rotation
- Trail integrity
- Orchestrator integration

Author: TITAN FUSE Team
Version: 5.0.0
"""

import os
import json
import hashlib
import base64
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from unittest import TestCase, mock

# Import the module under test
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from events.audit_signer import (
    # Enums and base classes
    SigningBackendType,
    SigningBackend,
    AuditSignerError,
    # Backends
    HMACBackend,
    RSABackend,
    KMSBackend,
    Ed25519Backend,
    # Data structures
    AuditEventV2,
    AuditTrailV2,
    SignedTrail,
    # Main class
    AuditSigner,
    # Factory functions
    create_audit_signer,
    sign_audit_event,
    verify_audit_event,
    generate_audit_trail,
    write_signed_trail,
    read_signed_trail,
    # Dependencies
    NACL_AVAILABLE,
    CRYPTO_AVAILABLE,
)


class TestHMACBackend(TestCase):
    """Tests for HMAC signing backend."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.secret_path = Path(self.temp_dir) / "hmac_secret"
    
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_hmac_signing_works(self):
        """Test that HMAC signing produces valid signatures."""
        backend = HMACBackend(secret="test-secret-key")
        
        data = b"test data to sign"
        signature = backend.sign(data)
        
        # Signature should be base64 encoded
        self.assertIsInstance(signature, str)
        
        # Should be able to decode as base64
        decoded = base64.b64decode(signature)
        self.assertEqual(len(decoded), 32)  # SHA-256 produces 32 bytes
    
    def test_hmac_verification_succeeds(self):
        """Test that HMAC verification succeeds for valid signatures."""
        backend = HMACBackend(secret="test-secret-key")
        
        data = b"test data to sign"
        signature = backend.sign(data)
        
        self.assertTrue(backend.verify(data, signature))
    
    def test_hmac_verification_fails_on_tampering(self):
        """Test that HMAC verification fails for tampered data."""
        backend = HMACBackend(secret="test-secret-key")
        
        data = b"test data to sign"
        signature = backend.sign(data)
        
        # Tamper with data
        tampered_data = b"test data to sign!"
        
        self.assertFalse(backend.verify(tampered_data, signature))
    
    def test_hmac_verification_fails_wrong_key(self):
        """Test that verification fails with wrong key."""
        backend1 = HMACBackend(secret="secret-1")
        backend2 = HMACBackend(secret="secret-2")
        
        data = b"test data"
        signature = backend1.sign(data)
        
        self.assertFalse(backend2.verify(data, signature))
    
    def test_hmac_key_rotation(self):
        """Test HMAC key rotation."""
        backend = HMACBackend(secret="old-secret")
        
        data = b"test data"
        old_signature = backend.sign(data)
        
        # Rotate key
        new_secret = backend.rotate_key()
        
        # Old signature should not verify
        self.assertFalse(backend.verify(data, old_signature))
        
        # New signature should work
        new_signature = backend.sign(data)
        self.assertTrue(backend.verify(data, new_signature))
    
    def test_hmac_secret_from_file(self):
        """Test loading HMAC secret from file."""
        secret_content = "file-based-secret-key"
        with open(self.secret_path, 'w') as f:
            f.write(secret_content)
        
        backend = HMACBackend(secret_path=str(self.secret_path))
        
        data = b"test data"
        signature = backend.sign(data)
        self.assertTrue(backend.verify(data, signature))
    
    def test_hmac_secret_generated_if_missing(self):
        """Test that secret is generated if file doesn't exist."""
        nonexistent = Path(self.temp_dir) / "nonexistent_secret"
        
        backend = HMACBackend(secret_path=str(nonexistent))
        
        # File should be created
        self.assertTrue(nonexistent.exists())
        
        # Should be able to sign
        data = b"test data"
        signature = backend.sign(data)
        self.assertTrue(backend.verify(data, signature))


class TestRSABackend(TestCase):
    """Tests for RSA signing backend."""
    
    def setUp(self):
        """Set up test fixtures."""
        if not CRYPTO_AVAILABLE:
            self.skipTest("cryptography library not available")
        
        self.temp_dir = tempfile.mkdtemp()
        self.private_key_path = Path(self.temp_dir) / "audit_private.pem"
        self.public_key_path = Path(self.temp_dir) / "audit_public.pem"
    
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_rsa_signing_works(self):
        """Test that RSA signing produces valid signatures."""
        backend = RSABackend()
        backend.generate_keypair(
            str(self.private_key_path),
            str(self.public_key_path)
        )
        
        data = b"test data to sign"
        signature = backend.sign(data)
        
        # Signature should be base64 encoded
        self.assertIsInstance(signature, str)
        
        # Should be able to decode as base64
        decoded = base64.b64decode(signature)
        self.assertEqual(len(decoded), 256)  # RSA-2048 produces 256 bytes
    
    def test_rsa_verification_succeeds(self):
        """Test that RSA verification succeeds for valid signatures."""
        backend = RSABackend()
        backend.generate_keypair()
        
        data = b"test data to sign"
        signature = backend.sign(data)
        
        self.assertTrue(backend.verify(data, signature))
    
    def test_rsa_verification_fails_on_tampering(self):
        """Test that RSA verification fails for tampered data."""
        backend = RSABackend()
        backend.generate_keypair()
        
        data = b"test data to sign"
        signature = backend.sign(data)
        
        # Tamper with data
        tampered_data = b"test data to sign!"
        
        self.assertFalse(backend.verify(tampered_data, signature))
    
    def test_rsa_key_generation(self):
        """Test RSA keypair generation."""
        backend = RSABackend()
        private_pem, public_pem = backend.generate_keypair(
            str(self.private_key_path),
            str(self.public_key_path)
        )
        
        # Should return PEM-encoded keys
        self.assertTrue(private_pem.startswith(b'-----BEGIN PRIVATE KEY-----'))
        self.assertTrue(public_pem.startswith(b'-----BEGIN PUBLIC KEY-----'))
        
        # Files should exist
        self.assertTrue(self.private_key_path.exists())
        self.assertTrue(self.public_key_path.exists())
    
    def test_rsa_key_loading(self):
        """Test loading RSA keys from files."""
        # Generate keys
        backend1 = RSABackend()
        backend1.generate_keypair(
            str(self.private_key_path),
            str(self.public_key_path)
        )
        
        data = b"test data"
        signature = backend1.sign(data)
        
        # Load keys in new backend
        backend2 = RSABackend(
            private_key_path=str(self.private_key_path),
            public_key_path=str(self.public_key_path)
        )
        
        # Should be able to verify with loaded keys
        self.assertTrue(backend2.verify(data, signature))
    
    def test_rsa_key_id_generation(self):
        """Test that RSA backend generates key IDs."""
        backend = RSABackend()
        backend.generate_keypair(
            str(self.private_key_path),
            str(self.public_key_path)
        )
        
        key_id = backend.get_key_id()
        self.assertIsNotNone(key_id)
        self.assertTrue(key_id.startswith("rsa-"))


class TestEd25519Backend(TestCase):
    """Tests for Ed25519 signing backend."""
    
    def setUp(self):
        """Set up test fixtures."""
        if not NACL_AVAILABLE:
            self.skipTest("pynacl library not available")
        
        self.temp_dir = tempfile.mkdtemp()
        self.key_path = Path(self.temp_dir) / "ed25519_key"
    
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_ed25519_signing_works(self):
        """Test that Ed25519 signing produces valid signatures."""
        backend = Ed25519Backend()
        backend.generate_keypair()
        
        data = b"test data to sign"
        signature = backend.sign(data)
        
        # Signature should be base64 encoded
        self.assertIsInstance(signature, str)
        
        # Should be able to decode as base64
        decoded = base64.b64decode(signature)
        self.assertEqual(len(decoded), 64)  # Ed25519 produces 64-byte signatures
    
    def test_ed25519_verification_succeeds(self):
        """Test that Ed25519 verification succeeds for valid signatures."""
        backend = Ed25519Backend()
        backend.generate_keypair()
        
        data = b"test data to sign"
        signature = backend.sign(data)
        
        self.assertTrue(backend.verify(data, signature))
    
    def test_ed25519_verification_fails_on_tampering(self):
        """Test that Ed25519 verification fails for tampered data."""
        backend = Ed25519Backend()
        backend.generate_keypair()
        
        data = b"test data to sign"
        signature = backend.sign(data)
        
        # Tamper with data
        tampered_data = b"test data to sign!"
        
        self.assertFalse(backend.verify(tampered_data, signature))
    
    def test_ed25519_key_generation(self):
        """Test Ed25519 keypair generation."""
        backend = Ed25519Backend()
        private_key, public_key = backend.generate_keypair()
        
        # Should return 32-byte keys
        self.assertEqual(len(private_key), 32)
        self.assertEqual(len(public_key), 32)
    
    def test_ed25519_key_saving_loading(self):
        """Test saving and loading Ed25519 keys."""
        # Generate and save
        backend1 = Ed25519Backend()
        backend1.generate_keypair()
        backend1.save_keypair(self.key_path)
        
        # Load in new backend
        backend2 = Ed25519Backend(key_path=str(self.key_path))
        
        # Should have same public key
        self.assertEqual(
            backend1.get_public_key(),
            backend2.get_public_key()
        )
    
    def test_ed25519_key_id(self):
        """Test Ed25519 key ID generation."""
        backend = Ed25519Backend()
        backend.generate_keypair()
        
        key_id = backend.get_key_id()
        self.assertIsNotNone(key_id)
        self.assertTrue(key_id.startswith("ed25519-"))


class TestKMSBackend(TestCase):
    """Tests for KMS signing backend."""
    
    def test_kms_not_configured(self):
        """Test KMS backend when not configured."""
        backend = KMSBackend()
        
        self.assertFalse(backend.is_available())
    
    def test_kms_configured_but_unavailable(self):
        """Test KMS backend when configured but service unavailable."""
        backend = KMSBackend(
            kms_endpoint="https://kms.example.com",
            key_id="test-key-id"
        )
        
        self.assertTrue(backend.is_available())
        
        # Signing should fail without actual KMS service
        with self.assertRaises(AuditSignerError):
            backend.sign(b"test data")
    
    @mock.patch('urllib.request.urlopen')
    def test_kms_signing_mocked(self, mock_urlopen):
        """Test KMS signing with mocked HTTP response."""
        # Mock the response
        mock_response = mock.MagicMock()
        mock_response.read.return_value = json.dumps({
            'signature': base64.b64encode(b'mock-signature').decode('ascii')
        }).encode('utf-8')
        mock_response.__enter__ = mock.MagicMock(return_value=mock_response)
        mock_response.__exit__ = mock.MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response
        
        backend = KMSBackend(
            kms_endpoint="https://kms.example.com",
            key_id="test-key-id",
            api_key="test-api-key"
        )
        
        signature = backend.sign(b"test data")
        self.assertEqual(signature, base64.b64encode(b'mock-signature').decode('ascii'))
    
    @mock.patch('urllib.request.urlopen')
    def test_kms_verification_mocked(self, mock_urlopen):
        """Test KMS verification with mocked HTTP response."""
        # Mock the response
        mock_response = mock.MagicMock()
        mock_response.read.return_value = json.dumps({'valid': True}).encode('utf-8')
        mock_response.__enter__ = mock.MagicMock(return_value=mock_response)
        mock_response.__exit__ = mock.MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response
        
        backend = KMSBackend(
            kms_endpoint="https://kms.example.com",
            key_id="test-key-id"
        )
        
        result = backend.verify(b"test data", "test-signature")
        self.assertTrue(result)


class TestAuditDataStructures(TestCase):
    """Tests for audit data structures."""
    
    def test_audit_event_creation(self):
        """Test AuditEventV2 creation."""
        event = AuditEventV2(
            event_id="evt-001",
            event_type="GATE_PASS",
            timestamp="2024-01-01T00:00:00Z",
            session_id="sess-001",
            data={"gate": "GATE-01"}
        )
        
        self.assertEqual(event.event_id, "evt-001")
        self.assertEqual(event.event_type, "GATE_PASS")
    
    def test_audit_event_hash(self):
        """Test AuditEventV2 hash computation."""
        event = AuditEventV2(
            event_id="evt-001",
            event_type="GATE_PASS",
            timestamp="2024-01-01T00:00:00Z",
            session_id="sess-001",
            data={"gate": "GATE-01"}
        )
        
        event_hash = event.compute_hash()
        
        # Should be SHA-256 hex digest
        self.assertEqual(len(event_hash), 64)
        self.assertTrue(all(c in '0123456789abcdef' for c in event_hash))
    
    def test_audit_event_serialization(self):
        """Test AuditEventV2 serialization."""
        event = AuditEventV2(
            event_id="evt-001",
            event_type="GATE_PASS",
            timestamp="2024-01-01T00:00:00Z",
            session_id="sess-001",
            data={"gate": "GATE-01"},
            event_hash="abc123",
            signature="sig123"
        )
        
        data = event.to_dict()
        
        self.assertEqual(data['event_id'], "evt-001")
        self.assertEqual(data['signature'], "sig123")
        
        # Round-trip
        restored = AuditEventV2.from_dict(data)
        self.assertEqual(restored.event_id, event.event_id)
    
    def test_audit_trail_creation(self):
        """Test AuditTrailV2 creation."""
        trail = AuditTrailV2(
            trail_id="trail-001",
            session_id="sess-001"
        )
        
        self.assertEqual(trail.trail_id, "trail-001")
        self.assertEqual(len(trail.events), 0)
    
    def test_audit_trail_add_event(self):
        """Test adding events to AuditTrailV2."""
        trail = AuditTrailV2(
            trail_id="trail-001",
            session_id="sess-001"
        )
        
        event = AuditEventV2(
            event_id="evt-001",
            event_type="GATE_PASS",
            timestamp="2024-01-01T00:00:00Z",
            session_id="sess-001",
            data={"gate": "GATE-01"}
        )
        
        trail.add_event(event)
        
        self.assertEqual(len(trail.events), 1)
        self.assertIsNotNone(trail.checksum)
        self.assertEqual(event.event_hash, event.compute_hash())
    
    def test_audit_trail_checksum(self):
        """Test AuditTrailV2 checksum computation."""
        trail = AuditTrailV2(
            trail_id="trail-001",
            session_id="sess-001"
        )
        
        # Add two events
        for i in range(2):
            event = AuditEventV2(
                event_id=f"evt-{i}",
                event_type="GATE_PASS",
                timestamp=f"2024-01-01T00:00:0{i}Z",
                session_id="sess-001",
                data={"gate": f"GATE-0{i}"}
            )
            trail.add_event(event)
        
        # Checksum should be SHA-256 of event hashes
        self.assertEqual(len(trail.checksum), 64)
    
    def test_signed_trail_creation(self):
        """Test SignedTrail creation."""
        trail = AuditTrailV2(
            trail_id="trail-001",
            session_id="sess-001"
        )
        
        signed = SignedTrail(
            trail=trail,
            signature="test-signature",
            signed_at="2024-01-01T00:00:00Z",
            backend_type="hmac"
        )
        
        self.assertEqual(signed.signature, "test-signature")
        self.assertEqual(signed.backend_type, "hmac")
    
    def test_signed_trail_serialization(self):
        """Test SignedTrail serialization."""
        trail = AuditTrailV2(
            trail_id="trail-001",
            session_id="sess-001"
        )
        
        signed = SignedTrail(
            trail=trail,
            signature="test-signature",
            signed_at="2024-01-01T00:00:00Z",
            backend_type="hmac",
            public_key_id="key-001"
        )
        
        data = signed.to_dict()
        
        self.assertEqual(data['signature'], "test-signature")
        self.assertEqual(data['backend_type'], "hmac")
        self.assertEqual(data['public_key_id'], "key-001")
        
        # Round-trip
        restored = SignedTrail.from_dict(data)
        self.assertEqual(restored.signature, signed.signature)


class TestAuditSigner(TestCase):
    """Tests for the main AuditSigner class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.config = {
            'audit': {
                'enabled': True,
                'backend': 'hmac',
                'hmac': {
                    'secret_path': str(Path(self.temp_dir) / "hmac_secret")
                },
                'trail_path': str(Path(self.temp_dir) / "audit_trail.json")
            }
        }
    
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_audit_signer_creation_hmac(self):
        """Test creating AuditSigner with HMAC backend."""
        signer = AuditSigner(config=self.config)
        
        self.assertEqual(signer.get_backend_type(), 'hmac')
    
    def test_audit_signer_sign_trail(self):
        """Test signing an audit trail."""
        signer = AuditSigner(config=self.config)
        
        trail = AuditTrailV2(
            trail_id="trail-001",
            session_id="sess-001"
        )
        
        event = AuditEventV2(
            event_id="evt-001",
            event_type="GATE_PASS",
            timestamp="2024-01-01T00:00:00Z",
            session_id="sess-001",
            data={"gate": "GATE-01"}
        )
        trail.add_event(event)
        
        signed = signer.sign_trail(trail)
        
        self.assertIsInstance(signed, SignedTrail)
        self.assertIsNotNone(signed.signature)
        self.assertEqual(signed.backend_type, 'hmac')
    
    def test_audit_signer_verify_trail(self):
        """Test verifying a signed audit trail."""
        signer = AuditSigner(config=self.config)
        
        trail = AuditTrailV2(
            trail_id="trail-001",
            session_id="sess-001"
        )
        
        event = AuditEventV2(
            event_id="evt-001",
            event_type="GATE_PASS",
            timestamp="2024-01-01T00:00:00Z",
            session_id="sess-001",
            data={"gate": "GATE-01"}
        )
        trail.add_event(event)
        
        signed = signer.sign_trail(trail)
        
        self.assertTrue(signer.verify_trail(signed))
    
    def test_audit_signer_verify_fails_on_tampering(self):
        """Test that verification fails for tampered trails."""
        signer = AuditSigner(config=self.config)
        
        trail = AuditTrailV2(
            trail_id="trail-001",
            session_id="sess-001"
        )
        
        event = AuditEventV2(
            event_id="evt-001",
            event_type="GATE_PASS",
            timestamp="2024-01-01T00:00:00Z",
            session_id="sess-001",
            data={"gate": "GATE-01"}
        )
        trail.add_event(event)
        
        signed = signer.sign_trail(trail)
        
        # Tamper with the trail
        signed.trail.session_id = "tampered-session"
        
        self.assertFalse(signer.verify_trail(signed))
    
    def test_audit_signer_key_rotation(self):
        """Test key rotation."""
        signer = AuditSigner(config=self.config)
        
        # Sign with original key
        trail = AuditTrailV2(
            trail_id="trail-001",
            session_id="sess-001"
        )
        signed = signer.sign_trail(trail)
        
        # Rotate key
        result = signer.rotate_key()
        
        self.assertEqual(result['backend'], 'hmac')
        
        # Old signature should no longer verify
        self.assertFalse(signer.verify_trail(signed))
        
        # New signature should work
        signed2 = signer.sign_trail(trail)
        self.assertTrue(signer.verify_trail(signed2))
    
    def test_audit_signer_critical_events(self):
        """Test critical event detection."""
        signer = AuditSigner(config=self.config)
        
        self.assertTrue(signer.is_critical_event('GATE_PASS'))
        self.assertTrue(signer.is_critical_event('GATE_FAIL'))
        self.assertTrue(signer.is_critical_event('CHECKPOINT_SAVE'))
        self.assertTrue(signer.is_critical_event('CREDENTIAL_ACCESS'))
        self.assertFalse(signer.is_critical_event('LOG_WRITE'))


class TestAuditSignerRSA(TestCase):
    """Tests for AuditSigner with RSA backend."""
    
    def setUp(self):
        """Set up test fixtures."""
        if not CRYPTO_AVAILABLE:
            self.skipTest("cryptography library not available")
        
        self.temp_dir = tempfile.mkdtemp()
        self.config = {
            'audit': {
                'enabled': True,
                'backend': 'rsa',
                'rsa': {
                    'private_key_path': str(Path(self.temp_dir) / "audit_private.pem"),
                    'public_key_path': str(Path(self.temp_dir) / "audit_public.pem")
                },
                'trail_path': str(Path(self.temp_dir) / "audit_trail.json")
            }
        }
    
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_rsa_backend_initialization(self):
        """Test RSA backend initialization."""
        signer = AuditSigner(config=self.config)
        
        self.assertEqual(signer.get_backend_type(), 'rsa')
        
        # Keys should be generated
        private_path = Path(self.config['audit']['rsa']['private_key_path'])
        public_path = Path(self.config['audit']['rsa']['public_key_path'])
        
        self.assertTrue(private_path.exists())
        self.assertTrue(public_path.exists())
    
    def test_rsa_signing_works(self):
        """Test RSA signing."""
        signer = AuditSigner(config=self.config)
        
        trail = AuditTrailV2(
            trail_id="trail-001",
            session_id="sess-001"
        )
        
        signed = signer.sign_trail(trail)
        
        self.assertEqual(signed.backend_type, 'rsa')
        self.assertTrue(signer.verify_trail(signed))


class TestFactoryFunctions(TestCase):
    """Tests for factory and utility functions."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_create_audit_signer(self):
        """Test create_audit_signer factory function."""
        config = {
            'audit': {
                'backend': 'hmac',
                'hmac': {'secret': 'test-secret'}
            }
        }
        
        signer = create_audit_signer(config)
        
        self.assertIsInstance(signer, AuditSigner)
        self.assertEqual(signer.get_backend_type(), 'hmac')
    
    def test_sign_audit_event(self):
        """Test sign_audit_event function."""
        signer = AuditSigner(backend_type='hmac', secret='test-secret')
        
        event = {'type': 'TEST', 'data': {'key': 'value'}}
        signed = sign_audit_event(event, signer)
        
        self.assertIn('signature', signed)
        self.assertIn('signed_at', signed)
        self.assertIn('backend_type', signed)
    
    def test_verify_audit_event(self):
        """Test verify_audit_event function."""
        signer = AuditSigner(backend_type='hmac', secret='test-secret')
        
        event = {'type': 'TEST', 'data': {'key': 'value'}}
        signed = sign_audit_event(event, signer)
        
        self.assertTrue(verify_audit_event(signed, signer))
    
    def test_generate_audit_trail(self):
        """Test generate_audit_trail function."""
        events = [
            {'type': 'GATE_PASS', 'data': {'gate': 'GATE-01'}},
            {'type': 'GATE_PASS', 'data': {'gate': 'GATE-02'}}
        ]
        
        trail = generate_audit_trail('sess-001', events)
        
        self.assertEqual(trail.session_id, 'sess-001')
        self.assertEqual(len(trail.events), 2)
    
    def test_write_and_read_signed_trail(self):
        """Test write_signed_trail and read_signed_trail functions."""
        signer = AuditSigner(backend_type='hmac', secret='test-secret')
        
        trail = AuditTrailV2(
            trail_id="trail-001",
            session_id="sess-001"
        )
        
        signed = signer.sign_trail(trail)
        
        # Write to file
        trail_path = Path(self.temp_dir) / "audit_trail.json"
        write_signed_trail(signed, str(trail_path))
        
        # Read back
        restored = read_signed_trail(str(trail_path))
        
        self.assertEqual(restored.signature, signed.signature)
        self.assertEqual(restored.trail.trail_id, trail.trail_id)


class TestTrailIntegrity(TestCase):
    """Tests for audit trail integrity."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_trail_hash_chain(self):
        """Test that events form a hash chain."""
        trail = AuditTrailV2(
            trail_id="trail-001",
            session_id="sess-001"
        )
        
        events = []
        for i in range(5):
            event = AuditEventV2(
                event_id=f"evt-{i}",
                event_type="GATE_PASS",
                timestamp=f"2024-01-01T00:00:0{i}Z",
                session_id="sess-001",
                data={"index": i}
            )
            trail.add_event(event)
            events.append(event)
        
        # Verify chain
        for i in range(1, len(trail.events)):
            self.assertEqual(
                trail.events[i].previous_hash,
                trail.events[i-1].event_hash
            )
    
    def test_trail_checksum_changes_on_event_add(self):
        """Test that checksum changes when events are added."""
        trail = AuditTrailV2(
            trail_id="trail-001",
            session_id="sess-001"
        )
        
        # Empty trail has no checksum
        initial_checksum = trail.checksum
        
        # Add event
        event = AuditEventV2(
            event_id="evt-001",
            event_type="GATE_PASS",
            timestamp="2024-01-01T00:00:00Z",
            session_id="sess-001",
            data={}
        )
        trail.add_event(event)
        
        # Checksum should be set
        self.assertIsNotNone(trail.checksum)
        first_checksum = trail.checksum
        
        # Add another event
        event2 = AuditEventV2(
            event_id="evt-002",
            event_type="GATE_PASS",
            timestamp="2024-01-01T00:00:01Z",
            session_id="sess-001",
            data={}
        )
        trail.add_event(event2)
        
        # Checksum should change
        self.assertNotEqual(trail.checksum, first_checksum)


class TestBackwardsCompatibility(TestCase):
    """Tests for backwards compatibility with original audit_signer."""
    
    def test_original_sign_audit_event_still_works(self):
        """Test that original sign_audit_event function still works."""
        from events.audit_signer import sign_audit_event as original_sign
        
        event = {'type': 'TEST', 'data': {}}
        
        # Should work without a signer (creates ephemeral)
        signed = original_sign(event)
        
        self.assertIn('signature', signed)
    
    def test_original_functions_preserved(self):
        """Test that original utility functions are preserved."""
        from events.audit_signer import (
            sign_audit_event,
            verify_audit_event,
            create_audit_signer,
        )
        
        # All should be callable
        self.assertTrue(callable(sign_audit_event))
        self.assertTrue(callable(verify_audit_event))
        self.assertTrue(callable(create_audit_signer))


if __name__ == '__main__':
    import unittest
    unittest.main()
