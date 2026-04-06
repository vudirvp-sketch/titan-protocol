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
