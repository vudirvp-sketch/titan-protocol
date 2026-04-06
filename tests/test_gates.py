"""
TITAN FUSE Protocol - Gate Tests

Unit tests for GATE validation.
"""

import pytest
from pathlib import Path
import sys
import tempfile
import os

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from state.state_manager import StateManager
from harness.orchestrator import Orchestrator


@pytest.fixture
def mock_repo(tmp_path):
    """Create mock repository structure."""
    # Create directories
    (tmp_path / "inputs").mkdir()
    (tmp_path / "outputs").mkdir()
    (tmp_path / "checkpoints").mkdir()
    (tmp_path / "sessions").mkdir()

    # Create test input file
    test_file = tmp_path / "inputs" / "test.md"
    test_file.write_text("# Test File\n\n" + "\n".join(f"Line {i}" for i in range(1, 100)))

    # Create minimal config
    import yaml
    config = {
        "session": {"max_tokens": 100000, "max_time_minutes": 60},
        "chunking": {"default_size": 1500},
        "validation": {"max_patch_iterations": 2}
    }
    with open(tmp_path / "config.yaml", "w") as f:
        yaml.dump(config, f)

    return tmp_path


class TestStateManager:
    """Tests for StateManager."""

    def test_create_session(self, mock_repo):
        """Test session creation."""
        manager = StateManager(mock_repo)
        session = manager.create_session()

        assert session is not None
        assert "id" in session
        assert session["status"] == "INITIALIZED"
        assert session["protocol_version"] == "3.2.0"

    def test_create_session_with_input(self, mock_repo):
        """Test session creation with input file."""
        manager = StateManager(mock_repo)
        input_file = str(mock_repo / "inputs" / "test.md")

        session = manager.create_session(input_files=[input_file])

        assert session["source_file"] == input_file
        assert session["source_checksum"] is not None

    def test_checkpoint_save_load(self, mock_repo):
        """Test checkpoint save and load."""
        manager = StateManager(mock_repo)
        session = manager.create_session(max_tokens=50000)

        # Save checkpoint
        result = manager.save_checkpoint()
        assert result["success"] is True

        # Clear and resume
        manager.current_session = None
        resume_result = manager.resume_from_checkpoint(result["checkpoint_path"])

        assert resume_result["success"] is True
        assert resume_result["session_id"] == session["id"]


class TestOrchestrator:
    """Tests for Orchestrator."""

    def test_validate_gate_00_pass(self, mock_repo):
        """Test GATE-00 passes with valid input."""
        manager = StateManager(mock_repo)
        input_file = str(mock_repo / "inputs" / "test.md")
        session = manager.create_session(input_files=[input_file])

        # Add chunks (simulating chunking phase)
        session["chunks"] = {
            "C1": {"chunk_id": "C1", "status": "PENDING", "line_start": 0, "line_end": 50},
            "C2": {"chunk_id": "C2", "status": "PENDING", "line_start": 50, "line_end": 100}
        }

        orchestrator = Orchestrator(mock_repo)
        passed, details = orchestrator.validate_gate("GATE-00", session)

        assert passed is True
        assert details["gate"] == "GATE-00"

    def test_validate_gate_00_fail_no_source(self, mock_repo):
        """Test GATE-00 fails without source file."""
        manager = StateManager(mock_repo)
        session = manager.create_session()

        orchestrator = Orchestrator(mock_repo)
        passed, details = orchestrator.validate_gate("GATE-00", session)

        assert passed is False

    def test_validate_gate_03_budget_check(self, mock_repo):
        """Test GATE-03 budget validation."""
        manager = StateManager(mock_repo)
        session = manager.create_session(max_tokens=100000)

        # Simulate budget exceeded
        session["tokens_used"] = 95000
        session["state_snapshot"] = {"execution_plan": {"batches": []}}

        orchestrator = Orchestrator(mock_repo)
        passed, details = orchestrator.validate_gate("GATE-03", session)

        assert passed is False
        assert any("Budget" in str(c) for c in details.get("checks", []))

    def test_validate_gate_04_sev1_block(self, mock_repo):
        """Test GATE-04 blocks with SEV-1 gaps."""
        manager = StateManager(mock_repo)
        session = manager.create_session()

        session["known_gaps"] = ["gap: SEV-1 critical issue found"]
        session["open_issues"] = ["ISSUE-001"]

        orchestrator = Orchestrator(mock_repo)
        passed, details = orchestrator.validate_gate("GATE-04", session)

        assert passed is False

    def test_phase_init(self, mock_repo):
        """Test PHASE 0 initialization."""
        manager = StateManager(mock_repo)
        session = manager.create_session()

        orchestrator = Orchestrator(mock_repo)
        result = orchestrator._phase_init(session)

        assert result["success"] is True
        assert "chunks" in result


class TestMockLLM:
    """Tests for Mock LLM."""

    def test_deterministic_responses(self):
        """Test that same seed produces same response."""
        from testing.mock_llm import MockLLMResponse

        mock1 = MockLLMResponse(seed=42)
        mock2 = MockLLMResponse(seed=42)

        r1 = mock1.query("Analyze code", context="test")
        r2 = mock2.query("Analyze code", context="test")

        assert r1["content"] == r2["content"]
        assert r1["_seed"] == r2["_seed"]

    def test_different_seeds(self):
        """Test that different seeds produce different responses."""
        from testing.mock_llm import MockLLMResponse

        mock1 = MockLLMResponse(seed=42)
        mock2 = MockLLMResponse(seed=43)

        r1 = mock1.query("Analyze code", context="test")
        r2 = mock2.query("Analyze code", context="test")

        assert r1["_seed"] != r2["_seed"]


class TestMockTools:
    """Tests for Mock Tools."""

    def test_grep_returns_results(self):
        """Test mock grep returns results."""
        from testing.mock_tools import MockToolRegistry

        mock = MockToolRegistry(seed=42)
        result = mock.call("grep", pattern="TODO", path=".")

        assert "matches" in result
        assert "count" in result
        assert result["count"] >= 0

    def test_file_operations(self):
        """Test mock file operations."""
        from testing.mock_tools import MockToolRegistry

        mock = MockToolRegistry()

        # Write
        mock.call("write", path="test.py", content="print('hello')")

        # Read
        result = mock.call("read", path="test.py")
        assert result["content"] == "print('hello')"

        # Checksum
        checksum = mock.call("checksum", path="test.py")
        assert "checksum" in checksum


class TestParityAudit:
    """Tests for Parity Audit."""

    def test_audit_runs(self, mock_repo):
        """Test that parity audit runs without errors."""
        from testing.parity_audit import ParityAudit

        # Create minimal PROTOCOL.base.md
        protocol_path = mock_repo / "PROTOCOL.base.md"
        protocol_path.write_text("""
# TITAN FUSE Protocol

## TIER 0
## TIER 1
## TIER 2
## TIER 3
## TIER 4
## TIER 5

GATE-00 GATE-01 GATE-02 GATE-03 GATE-04 GATE-05
INVAR-01 INVAR-02 INVAR-03 INVAR-04
""")

        # Create src directory
        src_path = mock_repo / "src"
        src_path.mkdir(exist_ok=True)

        audit = ParityAudit(protocol_path, src_path)
        result = audit.audit()

        assert "passed" in result
        assert "results" in result
        assert len(result["results"]) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# =============================================================================
# NEW in v3.2: Tests for recursion, telemetry, confidence, and security
# =============================================================================

class TestRecursionControl:
    """Tests for recursion depth control (NEW in v3.2)."""

    def test_recursion_increment(self, mock_repo):
        """Test recursion depth increment."""
        manager = StateManager(mock_repo)
        manager.create_session()
        
        # Should succeed initially
        assert manager.increment_recursion_depth() is True
        assert manager.current_session.recursion_depth == 1
        
        # Should fail at limit (max is 1 by default)
        assert manager.increment_recursion_depth() is False
        assert manager.current_session.recursion_depth == 1

    def test_recursion_decrement(self, mock_repo):
        """Test recursion depth decrement."""
        manager = StateManager(mock_repo)
        manager.create_session()
        
        manager.increment_recursion_depth()
        assert manager.current_session.recursion_depth == 1
        
        manager.decrement_recursion_depth()
        assert manager.current_session.recursion_depth == 0

    def test_recursion_peak_tracking(self, mock_repo):
        """Test recursion peak is tracked."""
        manager = StateManager(mock_repo)
        manager.create_session()
        
        manager.increment_recursion_depth()
        manager.decrement_recursion_depth()
        
        assert manager.current_session.recursion_depth_peak == 1


class TestTokenTelemetry:
    """Tests for token telemetry (NEW in v3.2)."""

    def test_record_query_metrics(self, mock_repo):
        """Test recording query metrics."""
        manager = StateManager(mock_repo)
        manager.create_session()
        
        manager.record_query_metrics(tokens=100, latency_ms=50, model_type="leaf")
        manager.record_query_metrics(tokens=200, latency_ms=75, model_type="root")
        
        assert len(manager.current_session.token_history) == 2
        assert len(manager.current_session.latency_history) == 2
        assert manager.current_session.leaf_model_calls == 1
        assert manager.current_session.root_model_calls == 1

    def test_token_percentiles(self, mock_repo):
        """Test p50/p95 percentile calculation."""
        manager = StateManager(mock_repo)
        manager.create_session()
        
        # Record 20 queries
        for i in range(1, 21):
            manager.record_query_metrics(tokens=i * 100, latency_ms=i * 10)
        
        percentiles = manager.get_token_percentiles()
        
        assert percentiles["p50"] > 0
        assert percentiles["p95"] > 0
        assert percentiles["total_queries"] == 20


class TestConfidenceTracking:
    """Tests for confidence tracking (NEW in v3.2)."""

    def test_record_confidence(self, mock_repo):
        """Test recording confidence scores."""
        manager = StateManager(mock_repo)
        manager.create_session()
        
        manager.record_confidence("HIGH")
        manager.record_confidence("HIGH")
        manager.record_confidence("MED")
        
        assert len(manager.current_session.confidence_scores) == 3
        assert manager.current_session.all_high_confidence is False

    def test_all_high_confidence(self, mock_repo):
        """Test all HIGH confidence tracking."""
        manager = StateManager(mock_repo)
        manager.create_session()
        
        manager.record_confidence("HIGH")
        manager.record_confidence("HIGH")
        
        assert manager.current_session.all_high_confidence is True

    def test_confidence_summary(self, mock_repo):
        """Test confidence summary."""
        manager = StateManager(mock_repo)
        manager.create_session()
        
        manager.record_confidence("HIGH")
        manager.record_confidence("MED")
        manager.record_confidence("LOW")
        
        summary = manager.get_confidence_summary()
        
        assert summary["high_count"] == 1
        assert summary["med_count"] == 1
        assert summary["low_count"] == 1


class TestExecutionGate:
    """Tests for Execution Gate (INVAR-05, NEW in v3.2)."""

    def test_disabled_mode(self):
        """Test execution is blocked in disabled mode."""
        from security.execution_gate import ExecutionGate, ExecutionMode
        
        gate = ExecutionGate({"execution_mode": "disabled"})
        result = gate.check_execution_allowed("print('hello')", "python")
        
        assert result.allowed is False
        assert "disabled" in result.reason.lower()

    def test_human_gate_mode(self):
        """Test human gate requires approval."""
        from security.execution_gate import ExecutionGate, ExecutionMode
        
        gate = ExecutionGate({"execution_mode": "human_gate"})
        result = gate.check_execution_allowed("print('hello')", "python")
        
        assert result.allowed is False
        assert result.requires_approval is True
        assert result.approval_token is not None

    def test_approval_flow(self):
        """Test approval flow."""
        from security.execution_gate import ExecutionGate
        
        gate = ExecutionGate({"execution_mode": "human_gate"})
        result = gate.check_execution_allowed("print('hello')", "python")
        
        # Not approved initially
        assert gate.is_approved(result.approval_token) is False
        
        # Approve
        gate.approve_execution(result.approval_token)
        assert gate.is_approved(result.approval_token) is True


class TestGate04ConfidenceAdvisory:
    """Tests for GATE-04 confidence advisory (NEW in v3.2)."""

    def test_confidence_advisory_no_gaps(self, mock_repo):
        """Test confidence advisory when all HIGH and no gaps."""
        manager = StateManager(mock_repo)
        session = manager.create_session()
        
        session["confidence_summary"] = {"all_high": True}
        session["known_gaps"] = []
        session["open_issues"] = []
        
        orchestrator = Orchestrator(mock_repo)
        passed, details = orchestrator.validate_gate("GATE-04", session)
        
        assert passed is True
        assert details.get("early_exit_eligible") is True

    def test_confidence_advisory_with_gaps(self, mock_repo):
        """Test confidence advisory ignored when gaps exist."""
        manager = StateManager(mock_repo)
        session = manager.create_session()
        
        session["confidence_summary"] = {"all_high": True}
        session["known_gaps"] = ["gap: SEV-3 some minor issue"]  # Non-blocking gap
        session["open_issues"] = ["ISSUE-001", "ISSUE-002", "ISSUE-003", "ISSUE-004", "ISSUE-005"]  # 5 issues, 1 gap = 20%
        
        orchestrator = Orchestrator(mock_repo)
        passed, details = orchestrator.validate_gate("GATE-04", session)
        
        # Should pass (gap is not SEV-1/SEV-2 and within threshold)
        assert passed is True
        # Should NOT be early exit eligible (gaps exist)
        assert details.get("early_exit_eligible") is None
