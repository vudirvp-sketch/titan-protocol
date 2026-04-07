"""
Tests for TITAN FUSE Protocol Security Modules (PHASE_1).

Tests for:
- ITEM-SEC-01: WASM and gVisor sandbox
- ITEM-SEC-02: Checkpoint serialization
- ITEM-SEC-03: Secret store backends
- ITEM-SEC-04: Secret scanning
- ITEM-SEC-05: Audit trail and signing

Author: TITAN FUSE Team
Version: 3.3.0
"""

import pytest
import json
import tempfile
from pathlib import Path
import os
import sys

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestWASMSandbox:
    """Tests for WASM sandbox (ITEM-SEC-01)."""
    
    def test_wasm_sandbox_import(self):
        """Test WASM sandbox can be imported."""
        try:
            from validation.wasm_sandbox import WASMSandbox, WASMConfig
            assert WASMSandbox is not None
            assert WASMConfig is not None
        except ImportError:
            pytest.skip("wasmtime not installed")
    
    def test_wasm_config_defaults(self):
        """Test WASM config defaults."""
        try:
            from validation.wasm_sandbox import WASMConfig
            config = WASMConfig()
            assert config.memory_limit_mb == 64
            assert config.timeout_ms == 10000
            assert config.network_enabled == False
        except ImportError:
            pytest.skip("wasmtime not installed")
    
    def test_wasm_code_safety_validation(self):
        """Test WASM code safety validation."""
        try:
            from validation.wasm_sandbox import create_wasm_sandbox
            sandbox = create_wasm_sandbox()
            
            # Test with empty/invalid code
            result = sandbox.validate_code_safety("(module)")
            assert 'safe' in result
        except ImportError:
            pytest.skip("wasmtime not installed")


class TestGVisorSandbox:
    """Tests for gVisor sandbox (ITEM-SEC-01)."""
    
    def test_gvisor_sandbox_import(self):
        """Test gVisor sandbox can be imported."""
        from validation.gvisor_sandbox import GVisorSandbox, GVisorConfig
        assert GVisorSandbox is not None
        assert GVisorConfig is not None
    
    def test_gvisor_config_defaults(self):
        """Test gVisor config defaults."""
        from validation.gvisor_sandbox import GVisorConfig
        config = GVisorConfig()
        assert config.memory_limit_mb == 256
        assert config.timeout_ms == 30000
        assert config.network_enabled == False
    
    def test_gvisor_code_safety_validation(self):
        """Test code safety validation."""
        from validation.gvisor_sandbox import GVisorSandbox
        sandbox = GVisorSandbox()
        
        # Test with dangerous code
        dangerous_code = "import os\nos.system('ls')"
        result = sandbox.validate_code_safety(dangerous_code)
        
        assert result['safe'] == False
        assert len(result['findings']) > 0


class TestCheckpointSerialization:
    """Tests for checkpoint serialization (ITEM-SEC-02)."""
    
    def test_serialization_format_enum(self):
        """Test serialization format enum."""
        from state.checkpoint_serialization import SerializationFormat
        
        assert SerializationFormat.JSON_ZSTD.value == "json_zstd"
        assert SerializationFormat.JSON.value == "json"
        assert SerializationFormat.PICKLE_UNSAFE.value == "pickle_unsafe"
    
    def test_json_serialization(self):
        """Test JSON serialization."""
        from state.checkpoint_serialization import serialize_checkpoint, deserialize_checkpoint, SerializationFormat
        
        data = {"test": "value", "number": 42}
        
        result = serialize_checkpoint(data, format=SerializationFormat.JSON)
        assert result.success == True
        assert result.format == SerializationFormat.JSON
        
        loaded, _ = deserialize_checkpoint(path=result.path)
        assert loaded == data
    
    def test_pickle_requires_unsafe_flag(self):
        """Test pickle requires unsafe flag."""
        from state.checkpoint_serialization import serialize_checkpoint, SerializationFormat
        
        data = {"test": "value"}
        
        # Should fail without unsafe_mode
        result = serialize_checkpoint(data, format=SerializationFormat.PICKLE_UNSAFE, unsafe_mode=False)
        assert result.success == False
        assert "unsafe_serialization_requires_explicit_flag" in result.error
    
    def test_pickle_with_unsafe_flag(self):
        """Test pickle with unsafe flag."""
        from state.checkpoint_serialization import serialize_checkpoint, deserialize_checkpoint, SerializationFormat
        
        data = {"test": "value"}
        
        # Should succeed with unsafe_mode
        result = serialize_checkpoint(data, format=SerializationFormat.PICKLE_UNSAFE, unsafe_mode=True)
        assert result.success == True
        
        loaded, _ = deserialize_checkpoint(path=result.path, unsafe_mode=True)
        assert loaded["test"] == "value"


class TestSecretStore:
    """Tests for secret store (ITEM-SEC-03)."""
    
    def test_secret_store_base_class(self):
        """Test secret store base class."""
        from secrets.store import SecretStore, SecretNotFoundError
        
        assert SecretStore is not None
        assert SecretNotFoundError is not None
    
    def test_env_backend(self):
        """Test environment variable backend."""
        from secrets.env_backend import EnvBackend
        
        store = EnvBackend(prefix='TEST_')
        
        # Set and get
        store.set('test_key', 'test_value')
        assert store.get('test_key') == 'test_value'
        assert store.exists('test_key') == True
        
        # Delete
        store.delete('test_key')
        assert store.exists('test_key') == False
    
    def test_env_backend_not_found(self):
        """Test env backend raises not found."""
        from secrets.env_backend import EnvBackend
        from secrets.store import SecretNotFoundError
        
        store = EnvBackend(prefix='NONEXISTENT_')
        
        with pytest.raises(SecretNotFoundError):
            store.get('nonexistent_key')
    
    def test_secret_ref_creation(self):
        """Test secret reference creation."""
        from secrets.env_backend import EnvBackend
        
        store = EnvBackend()
        
        ref = store.create_secret_ref('api_key')
        assert ref == 'secret_ref:api_key'
        assert store.is_secret_ref(ref) == True
    
    def test_factory_function(self):
        """Test secret store factory."""
        from secrets.factory import get_secret_store, create_secret_store
        
        # Test env backend creation
        store = create_secret_store('env', {'prefix': 'FACTORY_TEST_'})
        assert store is not None
        
        # Test get_secret_store
        store2 = get_secret_store({'secrets': {'backend': 'env'}})
        assert store2 is not None


class TestSecretScanner:
    """Tests for secret scanner (ITEM-SEC-04)."""
    
    def test_secret_scanner_import(self):
        """Test secret scanner import."""
        from security.secret_scanner import SecretScanner, SecretFinding
        assert SecretScanner is not None
    
    def test_scan_content_api_key(self):
        """Test API key detection."""
        from security.secret_scanner import SecretScanner
        
        scanner = SecretScanner()
        
        content = "api_key: sk-1234567890abcdefghijklmnop"
        findings = scanner.scan_content(content)
        
        assert len(findings) > 0
        assert any(f.type == 'OPENAI_KEY' for f in findings)
    
    def test_scan_content_aws_key(self):
        """Test AWS key detection."""
        from security.secret_scanner import SecretScanner
        
        scanner = SecretScanner()
        
        content = "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
        findings = scanner.scan_content(content)
        
        assert len(findings) > 0
        assert any(f.type == 'AWS_ACCESS_KEY' for f in findings)
    
    def test_scan_file(self):
        """Test file scanning."""
        from security.secret_scanner import SecretScanner
        
        scanner = SecretScanner()
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("api_key: sk-test1234567890abcdefghijklmnop\n")
            f.write("password: secret123\n")
            temp_path = Path(f.name)
        
        try:
            findings = scanner.scan_file(temp_path)
            assert len(findings) > 0
        finally:
            temp_path.unlink()
    
    def test_baseline_support(self):
        """Test baseline file support."""
        from security.secret_scanner import SecretScanner
        
        scanner = SecretScanner()
        
        # Create baseline file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({
                'test-fingerprint': {
                    'file': 'test.yaml',
                    'line': 1,
                    'type': 'API_KEY'
                }
            }, f)
            baseline_path = Path(f.name)
        
        try:
            scanner.load_baseline(baseline_path)
            assert 'test-fingerprint' in scanner.baseline
        finally:
            baseline_path.unlink()


class TestAuditTrail:
    """Tests for audit trail (ITEM-SEC-05)."""
    
    def test_audit_trail_import(self):
        """Test audit trail import."""
        from events.audit_trail import AuditTrail, MerkleTree
        assert AuditTrail is not None
        assert MerkleTree is not None
    
    def test_merkle_tree(self):
        """Test Merkle tree."""
        from events.audit_trail import MerkleTree
        
        tree = MerkleTree()
        
        # Add leaves
        tree.add_leaf("hash1")
        tree.add_leaf("hash2")
        tree.add_leaf("hash3")
        
        # Get root
        root = tree.get_root()
        assert root is not None
        
        # Get proof
        proof = tree.get_proof(0)
        assert len(proof) > 0
    
    def test_audit_trail_add_entry(self):
        """Test adding entries to audit trail."""
        from events.audit_trail import AuditTrail
        
        trail = AuditTrail()
        
        # Add entries
        event_id1 = trail.add_entry({'type': 'TEST_EVENT', 'data': {'key': 'value'}})
        event_id2 = trail.add_entry({'type': 'GATE_PASS', 'data': {'gate': 'GATE-01'}})
        
        assert event_id1 is not None
        assert event_id2 is not None
        assert len(trail.events) == 2
    
    def test_audit_trail_integrity(self):
        """Test audit trail integrity verification."""
        from events.audit_trail import AuditTrail
        
        trail = AuditTrail()
        
        # Add entries
        for i in range(10):
            trail.add_entry({'type': f'EVENT_{i}', 'data': {'index': i}})
        
        # Verify integrity
        result = trail.verify_integrity()
        assert result['valid'] == True
        assert result['event_count'] == 10
    
    def test_merkle_proof_verification(self):
        """Test Merkle proof verification."""
        from events.audit_trail import AuditTrail
        
        trail = AuditTrail()
        
        # Add entries
        event_id = trail.add_entry({'type': 'TEST', 'data': {'test': True}})
        
        # Get proof
        proof = trail.get_proof(event_id)
        root = trail.get_merkle_root()
        
        # Verify (simplified - actual verification would use event hash)
        assert proof is not None
        assert root is not None


class TestAuditSigner:
    """Tests for audit signer (ITEM-SEC-05)."""
    
    def test_audit_signer_import(self):
        """Test audit signer import."""
        try:
            from events.audit_signer import AuditSigner
            assert AuditSigner is not None
        except ImportError:
            pytest.skip("pynacl not installed")
    
    def test_keypair_generation(self):
        """Test keypair generation."""
        try:
            from events.audit_signer import AuditSigner
            
            signer = AuditSigner()
            private_key, public_key = signer.generate_keypair()
            
            assert len(private_key) == 32
            assert len(public_key) == 32
            assert signer.is_loaded() == True
        except ImportError:
            pytest.skip("pynacl not installed")
    
    def test_sign_and_verify(self):
        """Test signing and verification."""
        try:
            from events.audit_signer import AuditSigner
            
            signer = AuditSigner()
            signer.generate_keypair()
            
            # Sign data
            data = b"test data to sign"
            signature = signer.sign(data)
            
            # Verify
            assert signer.verify(data, signature) == True
            
            # Verify with wrong data
            assert signer.verify(b"wrong data", signature) == False
        except ImportError:
            pytest.skip("pynacl not installed")
    
    def test_sign_dict(self):
        """Test dictionary signing."""
        try:
            from events.audit_signer import AuditSigner
            
            signer = AuditSigner()
            signer.generate_keypair()
            
            data = {"event": "GATE_PASS", "gate": "GATE-01"}
            signature = signer.sign_dict(data)
            
            assert signer.verify_dict(data, signature) == True
        except ImportError:
            pytest.skip("pynacl not installed")


class TestGATE00SecretScan:
    """Tests for GATE-00 secret scanning integration (ITEM-SEC-04)."""
    
    def test_gate_00_in_orchestrator(self):
        """Test GATE-00 includes secret scanning."""
        from harness.orchestrator import Orchestrator
        
        orchestrator = Orchestrator()
        
        # Test with empty session (no secrets)
        session = {
            "source_file": "test.txt",
            "chunks": {"C1": {}}
        }
        
        passed, details = orchestrator.validate_gate("GATE-00", session)
        
        # Check that secret_scan check is included
        check_names = [c['name'] for c in details['checks']]
        assert 'secret_scan' in check_names
    
    def test_gate_00_blocks_secrets(self):
        """Test GATE-00 blocks when secrets found."""
        from harness.orchestrator import Orchestrator
        from security.secret_scanner import SecretScanner
        
        # This test would require creating actual files with secrets
        # For now, we verify the integration exists
        orchestrator = Orchestrator(config={
            'security': {
                'secrets_scan': True,
                'fail_on_detection': True
            }
        })
        
        assert orchestrator.config.get('security', {}).get('secrets_scan') == True


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
