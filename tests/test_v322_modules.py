"""
Tests for v3.2.2 modules: Secret Scanner, Sandbox Verifier,
Cycle Detector, Gap Object, and Schema Migrations.
"""

import pytest
from pathlib import Path
import sys
import tempfile
import os

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from state.gap import Gap, GapSeverity, convert_gaps_to_objects, convert_gaps_to_strings
from planning.cycle_detector import CycleDetector, validate_dag
from security.secret_scanner import SecretScanner
from security.sandbox_verifier import SandboxVerifier
from schema.migrations import apply_migrations, CURRENT_SCHEMA_VERSION


class TestGapObject:
    """Tests for structured Gap object."""
    
    def test_gap_creation(self):
        """Test basic gap creation."""
        gap = Gap(
            id="GAP-001",
            reason="Test gap",
            severity=GapSeverity.SEV_2
        )
        assert gap.id == "GAP-001"
        assert gap.reason == "Test gap"
        assert gap.severity == GapSeverity.SEV_2
        assert not gap.verified
    
    def test_gap_auto_id(self):
        """Test automatic ID generation."""
        gap = Gap(id="", reason="Auto ID test", source_file="test.py")
        assert gap.id.startswith("GAP-")
        assert len(gap.id) == 12  # GAP-XXXXXXXX
    
    def test_gap_to_string(self):
        """Test string conversion."""
        gap = Gap(
            id="GAP-001",
            reason="Test gap",
            severity=GapSeverity.SEV_1,
            source_line_start=10,
            source_line_end=20,
            source_checksum="abc123"
        )
        result = gap.to_string()
        assert "[gap:" in result
        assert "SEV-1" in result
        assert "source:10-20:abc123" in result
    
    def test_gap_from_string(self):
        """Test parsing from string."""
        gap_str = "[gap: Test reason (SEV-2) -- source:5-10:deadbeef]"
        gap = Gap.from_string(gap_str)
        
        assert gap.reason == "Test reason"
        assert gap.severity == GapSeverity.SEV_2
        assert gap.source_line_start == 5
        assert gap.source_line_end == 10
        assert gap.source_checksum == "deadbeef"
        assert gap.verified
    
    def test_convert_gaps_list(self):
        """Test list conversion."""
        strings = [
            "[gap: Issue 1 (SEV-1)]",
            "[gap: Issue 2 (SEV-3)]"
        ]
        gaps = convert_gaps_to_objects(strings)
        
        assert len(gaps) == 2
        assert gaps[0].severity == GapSeverity.SEV_1
        assert gaps[1].severity == GapSeverity.SEV_3
        
        back_to_strings = convert_gaps_to_strings(gaps)
        assert len(back_to_strings) == 2


class TestCycleDetector:
    """Tests for DAG cycle detection."""
    
    def test_no_cycle(self):
        """Test detection with no cycle."""
        detector = CycleDetector()
        detector.add_edge("A", "B")
        detector.add_edge("B", "C")
        detector.add_edge("A", "C")
        
        has_cycle, _ = detector.detect_cycle()
        assert not has_cycle
    
    def test_with_cycle(self):
        """Test detection with cycle."""
        detector = CycleDetector()
        detector.add_edge("A", "B")
        detector.add_edge("B", "C")
        detector.add_edge("C", "A")  # Creates cycle
        
        has_cycle, path = detector.detect_cycle()
        assert has_cycle
        assert len(path) >= 3  # A -> B -> C -> A
    
    def test_topological_sort(self):
        """Test topological ordering."""
        detector = CycleDetector()
        detector.add_edge("A", "B")
        detector.add_edge("B", "C")
        
        success, order = detector.topological_sort()
        assert success
        assert order.index("A") < order.index("B")
        assert order.index("B") < order.index("C")
    
    def test_validate_dag_function(self):
        """Test validate_dag convenience function."""
        edges = [("step1", "step2"), ("step2", "step3")]
        result = validate_dag(edges)
        
        assert result["valid"]
        assert len(result["order"]) == 3
    
    def test_validate_dag_with_cycle(self):
        """Test validate_dag with cycle."""
        edges = [("A", "B"), ("B", "C"), ("C", "A")]
        result = validate_dag(edges)
        
        assert not result["valid"]
        assert "cycle" in result


class TestSecretScanner:
    """Tests for secret scanning."""
    
    def test_aws_key_detection(self):
        """Test AWS access key detection."""
        scanner = SecretScanner()
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n')
            f.flush()
            
            findings = scanner.scan_file(Path(f.name))
            assert len(findings) > 0
            assert findings[0]["type"] == "AWS_ACCESS_KEY"
            
            os.unlink(f.name)
    
    def test_github_token_detection(self):
        """Test GitHub token detection."""
        scanner = SecretScanner()
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            f.write('github_token: ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\n')
            f.flush()
            
            findings = scanner.scan_file(Path(f.name))
            assert len(findings) > 0
            assert "GITHUB" in findings[0]["type"]
            
            os.unlink(f.name)
    
    def test_private_key_detection(self):
        """Test private key detection."""
        scanner = SecretScanner()
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pem', delete=False) as f:
            f.write('-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n')
            f.flush()
            
            findings = scanner.scan_file(Path(f.name))
            assert len(findings) > 0
            assert findings[0]["type"] == "PRIVATE_KEY"
            
            os.unlink(f.name)
    
    def test_clean_file(self):
        """Test clean file with no secrets."""
        scanner = SecretScanner()
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('def hello():\n    print("Hello, World!")\n')
            f.flush()
            
            findings = scanner.scan_file(Path(f.name))
            assert len(findings) == 0
            
            os.unlink(f.name)


class TestSandboxVerifier:
    """Tests for sandbox verification."""
    
    def test_trusted_mode(self):
        """Test trusted mode (no sandbox required)."""
        config = {"security": {"execution_mode": "trusted"}}
        verifier = SandboxVerifier(config)
        result = verifier.verify()
        
        assert result["verified"]
        assert result["mode"] == "trusted"
    
    def test_venv_check(self):
        """Test venv detection."""
        config = {"security": {"execution_mode": "trusted"}}
        verifier = SandboxVerifier(config)
        
        venv_check = verifier._check_venv()
        assert venv_check["name"] == "venv"
        assert venv_check["status"] in ["PASS", "WARN"]


class TestSchemaMigrations:
    """Tests for schema migrations."""
    
    def test_migrate_320_to_322(self):
        """Test full migration from 3.2.0 to 3.2.2."""
        old_checkpoint = {
            "protocol_version": "3.2.0",
            "known_gaps": ["[gap: test (SEV-2)]"]
        }
        
        migrated = apply_migrations(old_checkpoint)
        
        assert migrated["protocol_version"] == "3.2.2"
        assert "cursor_state" in migrated
        assert "gap_objects" in migrated
    
    def test_migrate_321_to_322(self):
        """Test migration from 3.2.1 to 3.2.2."""
        checkpoint = {
            "protocol_version": "3.2.1",
            "known_gaps": []
        }
        
        migrated = apply_migrations(checkpoint)
        
        assert migrated["protocol_version"] == "3.2.2"
        assert "readiness_tier" in migrated
        assert migrated["max_recursion_depth"] == 3


# Seed-based deterministic tests
@pytest.mark.parametrize("seed", [42, 123, 456])
def test_gap_id_deterministic(seed):
    """Test gap ID generation is deterministic with seed."""
    import random
    random.seed(seed)
    
    gap1 = Gap(id="", reason="Test", source_file="file.py")
    
    random.seed(seed)
    gap2 = Gap(id="", reason="Test", source_file="file.py")
    
    # IDs should be same for same input
    assert gap1.id == gap2.id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
