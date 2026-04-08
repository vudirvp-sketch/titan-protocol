"""
TITAN FUSE Protocol - Gate Pre/Post Validation Tests

ITEM-GATE-002: Tests for GATE_04 Pre/Post Split Validation

Tests the pre/post validation phases for GATE_04:
- Pre-validation runs before execution
- Post-validation runs after execution
- State is captured between pre/post
- Pre-validation failure blocks execution
- Post-validation failure returns FAIL

Author: TITAN FUSE Team
Version: 5.0.0
"""

import pytest
from pathlib import Path
import sys
import hashlib

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.policy.gate_manager import (
    GateManager,
    GateResult,
    GateType,
    PreValidationResult,
    PostValidationResult,
    GateManagerResult,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def gate_manager():
    """Create a GateManager instance for testing."""
    return GateManager()


@pytest.fixture
def valid_context():
    """Create a valid context for testing."""
    return {
        "policies": {"policy_1": {"enabled": True}},
        "user": {"permissions": ["read", "write"]},
        "required_permissions": ["read"],
        "input": {"data": "test"},
        "session_id": "test-session-123",
    }


@pytest.fixture
def mock_patch_executor_success():
    """Create a mock patch executor that succeeds."""
    def execute(context):
        return {
            "status": "success",
            "files_modified": ["file1.py", "file2.py"],
            "artifacts": {"artifact_1": "data"},
        }
    return execute


@pytest.fixture
def mock_patch_executor_failure():
    """Create a mock patch executor that fails."""
    def execute(context):
        raise RuntimeError("Patch execution failed")
    return execute


# =============================================================================
# PreValidationResult Tests
# =============================================================================

class TestPreValidationResult:
    """Tests for PreValidationResult dataclass."""
    
    def test_passed_property_true(self):
        """Test that passed property returns True when all checks pass."""
        result = PreValidationResult(
            validation_pass=True,
            idempotent_check=True,
            state_checksum="abc123",
            errors=[]
        )
        assert result.passed is True
    
    def test_passed_property_false_validation(self):
        """Test that passed property returns False when validation fails."""
        result = PreValidationResult(
            validation_pass=False,
            idempotent_check=True,
            state_checksum="abc123",
            errors=["Validation failed"]
        )
        assert result.passed is False
    
    def test_passed_property_false_idempotent(self):
        """Test that passed property returns False when idempotent check fails."""
        result = PreValidationResult(
            validation_pass=True,
            idempotent_check=False,
            state_checksum="abc123",
            errors=["Idempotent check failed"]
        )
        assert result.passed is False
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        result = PreValidationResult(
            validation_pass=True,
            idempotent_check=True,
            state_checksum="abc123",
            errors=[]
        )
        d = result.to_dict()
        
        assert d["validation_pass"] is True
        assert d["idempotent_check"] is True
        assert d["state_checksum"] == "abc123"
        assert d["passed"] is True
        assert d["errors"] == []


# =============================================================================
# PostValidationResult Tests
# =============================================================================

class TestPostValidationResult:
    """Tests for PostValidationResult dataclass."""
    
    def test_passed_property_true(self):
        """Test that passed property returns True when all checks pass."""
        result = PostValidationResult(
            orphan_scan=True,
            artifact_verify=True,
            gaps_found=[],
            errors=[]
        )
        assert result.passed is True
    
    def test_passed_property_false_orphan(self):
        """Test that passed property returns False when orphan scan fails."""
        result = PostValidationResult(
            orphan_scan=False,
            artifact_verify=True,
            gaps_found=[],
            errors=["Orphan references found"]
        )
        assert result.passed is False
    
    def test_passed_property_false_artifact(self):
        """Test that passed property returns False when artifact verification fails."""
        result = PostValidationResult(
            orphan_scan=True,
            artifact_verify=False,
            gaps_found=[],
            errors=["Missing artifacts"]
        )
        assert result.passed is False
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        result = PostValidationResult(
            orphan_scan=True,
            artifact_verify=True,
            gaps_found=["gap1", "gap2"],
            errors=[]
        )
        d = result.to_dict()
        
        assert d["orphan_scan"] is True
        assert d["artifact_verify"] is True
        assert d["gaps_found"] == ["gap1", "gap2"]
        assert d["passed"] is True
        assert d["errors"] == []


# =============================================================================
# Pre-Validation Tests
# =============================================================================

class TestPreGate04Validation:
    """Tests for _pre_gate_04_validation method."""
    
    def test_pre_validation_runs(self, gate_manager, valid_context):
        """Test that pre-validation runs successfully."""
        result = gate_manager._pre_gate_04_validation(valid_context)
        
        assert isinstance(result, PreValidationResult)
        assert result.validation_pass is True
        assert result.idempotent_check is True
        assert len(result.state_checksum) == 16  # Truncated SHA256
    
    def test_pre_validation_with_missing_policies(self, gate_manager):
        """Test pre-validation fails when policies are missing."""
        context = {
            "policies": {},  # Empty policies
            "input": {"data": "test"},
        }
        
        result = gate_manager._pre_gate_04_validation(context)
        
        assert result.validation_pass is False
        assert "One or more validators failed" in result.errors
    
    def test_pre_validation_with_duplicate_idempotency_key(self, gate_manager, valid_context):
        """Test pre-validation fails with duplicate idempotency key."""
        valid_context["idempotency_key"] = "key-123"
        valid_context["seen_idempotency_keys"] = {"key-123"}  # Already seen
        
        result = gate_manager._pre_gate_04_validation(valid_context)
        
        assert result.idempotent_check is False
        assert "Idempotent state check failed" in result.errors
    
    def test_state_captured(self, gate_manager, valid_context):
        """Test that state is captured during pre-validation."""
        result = gate_manager._pre_gate_04_validation(valid_context)
        
        # Verify checksum is generated
        assert result.state_checksum != ""
        assert len(result.state_checksum) == 16
        
        # Verify checksum is deterministic for same input
        result2 = gate_manager._pre_gate_04_validation(valid_context)
        assert result.state_checksum == result2.state_checksum
    
    def test_state_checksum_differs_for_different_input(self, gate_manager):
        """Test that state checksum differs for different inputs."""
        context1 = {"input": {"data": "test1"}, "policies": {"p1": {}}}
        context2 = {"input": {"data": "test2"}, "policies": {"p1": {}}}
        
        result1 = gate_manager._pre_gate_04_validation(context1)
        result2 = gate_manager._pre_gate_04_validation(context2)
        
        assert result1.state_checksum != result2.state_checksum


# =============================================================================
# Post-Validation Tests
# =============================================================================

class TestPostGate04Validation:
    """Tests for _post_gate_04_validation method."""
    
    def test_post_validation_runs(self, gate_manager):
        """Test that post-validation runs successfully."""
        context = {
            "output": {
                "status": "success",
                "files_modified": ["file1.py"],
            },
            "existing_files": ["file1.py"],
        }
        
        result = gate_manager._post_gate_04_validation(context)
        
        assert isinstance(result, PostValidationResult)
        assert result.orphan_scan is True
        assert result.artifact_verify is True
    
    def test_post_validation_detects_orphans(self, gate_manager):
        """Test that post-validation detects orphan references."""
        context = {
            "output": {
                "files_modified": ["file1.py", "orphan.py"],
            },
            "existing_files": ["file1.py"],  # Missing orphan.py
        }
        
        result = gate_manager._post_gate_04_validation(context)
        
        assert result.orphan_scan is False
        assert "Orphan references detected" in result.errors
    
    def test_post_validation_missing_artifacts(self, gate_manager):
        """Test that post-validation detects missing artifacts."""
        context = {
            "output": {},
            "required_artifacts": ["artifact_1", "artifact_2"],
            "artifacts": {"artifact_1": "data"},  # Missing artifact_2
        }
        
        result = gate_manager._post_gate_04_validation(context)
        
        assert result.artifact_verify is False
        assert "Artifact verification failed" in result.errors
    
    def test_post_validation_collects_gaps(self, gate_manager):
        """Test that post-validation collects gaps."""
        context = {
            "output": {},
            "gaps": [
                {"id": "gap-1", "severity": "SEV-3"},
                {"id": "gap-2", "severity": "SEV-4"},
            ],
        }
        
        result = gate_manager._post_gate_04_validation(context)
        
        assert len(result.gaps_found) == 2


# =============================================================================
# run_gate_04_with_prepost Tests
# =============================================================================

class TestRunGate04WithPrepost:
    """Tests for run_gate_04_with_prepost method."""
    
    def test_full_validation_success(
        self, 
        gate_manager, 
        valid_context, 
        mock_patch_executor_success
    ):
        """Test successful full pre/post validation."""
        # Add existing files to context for orphan check
        valid_context["existing_files"] = ["file1.py", "file2.py"]
        
        result = gate_manager.run_gate_04_with_prepost(
            valid_context, 
            mock_patch_executor_success
        )
        
        assert result.overall_result == GateResult.PASS
        assert len(result.failed_gates) == 0
    
    def test_pre_fail_blocks_execution(self, gate_manager, mock_patch_executor_success):
        """Test that pre-validation failure blocks execution."""
        # Create context that will fail pre-validation
        context = {
            "policies": {},  # Missing policies will fail
        }
        
        # Track if executor was called
        executor_called = [False]
        
        def tracked_executor(ctx):
            executor_called[0] = True
            return {"status": "success"}
        
        result = gate_manager.run_gate_04_with_prepost(context, tracked_executor)
        
        assert result.overall_result == GateResult.FAIL
        assert "GATE_04_PRE" in result.failed_gates
        assert executor_called[0] is False  # Executor should not be called
    
    def test_execution_failure_returns_fail(
        self, 
        gate_manager, 
        valid_context, 
        mock_patch_executor_failure
    ):
        """Test that execution failure returns FAIL."""
        result = gate_manager.run_gate_04_with_prepost(
            valid_context, 
            mock_patch_executor_failure
        )
        
        assert result.overall_result == GateResult.FAIL
        assert "GATE_04_EXECUTION" in result.failed_gates
        assert "Execution failed" in result.warnings[0]
    
    def test_post_fail_returns_fail(self, gate_manager, valid_context):
        """Test that post-validation failure returns FAIL."""
        # Create executor that produces orphan references
        def executor_with_orphans(ctx):
            return {
                "files_modified": ["existing.py", "orphan.py"],
            }
        
        # Only existing.py exists
        valid_context["existing_files"] = ["existing.py"]
        
        result = gate_manager.run_gate_04_with_prepost(
            valid_context, 
            executor_with_orphans
        )
        
        assert result.overall_result == GateResult.FAIL
        assert "GATE_04_POST" in result.failed_gates
    
    def test_gaps_included_in_warnings(
        self, 
        gate_manager, 
        valid_context, 
        mock_patch_executor_success
    ):
        """Test that gaps are included in warnings on success."""
        valid_context["gaps"] = [
            {"id": "gap-1", "severity": "SEV-3", "description": "Minor issue"},
        ]
        valid_context["existing_files"] = ["file1.py", "file2.py"]
        
        result = gate_manager.run_gate_04_with_prepost(
            valid_context, 
            mock_patch_executor_success
        )
        
        assert result.overall_result == GateResult.PASS
        assert len(result.warnings) == 1


# =============================================================================
# Helper Method Tests
# =============================================================================

class TestHelperMethods:
    """Tests for helper methods."""
    
    def test_run_all_validators_pass(self, gate_manager, valid_context):
        """Test _run_all_validators returns True for valid context."""
        result = gate_manager._run_all_validators(valid_context)
        assert result is True
    
    def test_run_all_validators_fail(self, gate_manager):
        """Test _run_all_validators returns False for invalid context."""
        context = {"policies": {}}  # Missing policies
        result = gate_manager._run_all_validators(context)
        assert result is False
    
    def test_check_idempotent_state_no_key(self, gate_manager):
        """Test _check_idempotent_state passes with no key."""
        context = {}
        result = gate_manager._check_idempotent_state(context)
        assert result is True
    
    def test_check_idempotent_state_duplicate_key(self, gate_manager):
        """Test _check_idempotent_state fails with duplicate key."""
        context = {
            "idempotency_key": "key-123",
            "seen_idempotency_keys": {"key-123"},
        }
        result = gate_manager._check_idempotent_state(context)
        assert result is False
    
    def test_check_idempotent_state_version_mismatch(self, gate_manager):
        """Test _check_idempotent_state fails with version mismatch."""
        context = {
            "idempotency_key": "key-123",
            "expected_state_version": "v1",
            "current_state_version": "v2",
        }
        result = gate_manager._check_idempotent_state(context)
        assert result is False
    
    def test_capture_state_checksum(self, gate_manager, valid_context):
        """Test _capture_state_checksum generates valid checksum."""
        checksum = gate_manager._capture_state_checksum(valid_context)
        
        assert len(checksum) == 16
        # Verify it's a hex string
        int(checksum, 16)
    
    def test_scan_orphan_references_no_refs(self, gate_manager):
        """Test _scan_orphan_references passes with no references."""
        context = {"output": {}}
        result = gate_manager._scan_orphan_references(context)
        assert result is True
    
    def test_scan_orphan_references_all_exist(self, gate_manager):
        """Test _scan_orphan_references passes when all files exist."""
        context = {
            "output": {"files_modified": ["file1.py", "file2.py"]},
            "existing_files": ["file1.py", "file2.py"],
        }
        result = gate_manager._scan_orphan_references(context)
        assert result is True
    
    def test_scan_orphan_references_orphans_found(self, gate_manager):
        """Test _scan_orphan_references fails when orphans found."""
        context = {
            "output": {"files_modified": ["file1.py", "orphan.py"]},
            "existing_files": ["file1.py"],
        }
        result = gate_manager._scan_orphan_references(context)
        assert result is False
    
    def test_verify_artifacts_no_requirements(self, gate_manager):
        """Test _verify_artifacts passes with no requirements."""
        context = {}
        result = gate_manager._verify_artifacts(context)
        assert result is True
    
    def test_verify_artifacts_all_present(self, gate_manager):
        """Test _verify_artifacts passes when all artifacts present."""
        context = {
            "required_artifacts": ["artifact_1", "artifact_2"],
            "artifacts": {"artifact_1": "data", "artifact_2": "data"},
        }
        result = gate_manager._verify_artifacts(context)
        assert result is True
    
    def test_verify_artifacts_missing(self, gate_manager):
        """Test _verify_artifacts fails when artifacts missing."""
        context = {
            "required_artifacts": ["artifact_1", "artifact_2"],
            "artifacts": {"artifact_1": "data"},  # Missing artifact_2
        }
        result = gate_manager._verify_artifacts(context)
        assert result is False
    
    def test_verify_artifacts_in_output(self, gate_manager):
        """Test _verify_artifacts finds artifacts in output."""
        context = {
            "required_artifacts": ["artifact_1"],
            "artifacts": {},  # Empty
            "output": {
                "artifacts": {"artifact_1": "data"},
            },
        }
        result = gate_manager._verify_artifacts(context)
        assert result is True


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests for GATE_04 pre/post validation."""
    
    def test_full_workflow_success(self, gate_manager):
        """Test complete successful workflow."""
        context = {
            "policies": {"policy_1": {"enabled": True}},
            "input": {"code": "def foo(): pass"},
            "session_id": "session-123",
            "existing_files": ["src/main.py"],
            "required_artifacts": ["report"],
        }
        
        def executor(ctx):
            return {
                "status": "success",
                "files_modified": ["src/main.py"],
                "artifacts": {"report": "generated"},
            }
        
        result = gate_manager.run_gate_04_with_prepost(context, executor)
        
        assert result.overall_result == GateResult.PASS
        assert len(result.failed_gates) == 0
    
    def test_full_workflow_with_gaps(self, gate_manager):
        """Test workflow that discovers gaps."""
        context = {
            "policies": {"policy_1": {"enabled": True}},
            "input": {"code": "def foo(): pass"},
            "session_id": "session-123",
            "existing_files": ["src/main.py"],
        }
        
        def executor(ctx):
            # Simulate discovering gaps during execution
            ctx["gaps"] = [
                {"id": "gap-1", "severity": "SEV-3", "description": "Missing docstring"},
            ]
            return {"status": "success"}
        
        result = gate_manager.run_gate_04_with_prepost(context, executor)
        
        assert result.overall_result == GateResult.PASS
        assert len(result.warnings) == 1


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
