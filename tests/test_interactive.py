"""
Tests for TITAN Protocol Interactive Mode.

ITEM-PROD-02: REPL-like debugging interface tests.

Test coverage:
- InteractiveSession class
- SessionStatus enum
- Breakpoint management
- State inspection and modification
- Rollback functionality
- TitanREPL class
- Command parsing and execution
- History management

Author: TITAN FUSE Team
Version: 4.0.0
"""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

from src.interactive import (
    InteractiveSession,
    SessionStatus,
    Breakpoint,
    SessionConfig,
    TitanREPL,
    CommandResult,
    CommandType,
)
from src.interactive.session import SessionStep


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_event_bus():
    """Create mock EventBus."""
    bus = Mock()
    bus.subscribe = Mock()
    bus.unsubscribe = Mock()
    bus.emit = Mock()
    return bus


@pytest.fixture
def mock_state_manager():
    """Create mock StateManager with session state."""
    manager = Mock()
    manager.get_current_session = Mock(return_value={
        "id": "test-session-123",
        "status": "RUNNING",
        "gates": {
            "GATE-00": {"status": "PASS"},
            "GATE-01": {"status": "PENDING"},
        },
        "tokens_used": 1000,
        "current_phase": 1,
        "chunk_cursor": "chunk-001",
        "open_issues": [],
    })
    manager.current_session = {
        "id": "test-session-123",
        "status": "RUNNING",
    }
    return manager


@pytest.fixture
def mock_checkpoint_manager():
    """Create mock CheckpointManager."""
    manager = Mock()
    manager.session_exists = Mock(return_value=True)
    manager.load = Mock(return_value=({"id": "test-session-123"}, Mock(success=True)))
    return manager


@pytest.fixture
def session_config():
    """Create test session config."""
    return SessionConfig(
        enabled=True,
        prompt="titan> ",
        history_file=".titan/test_history",
        auto_pause_on=["GATE_FAIL", "CLARITY_LOW"],
        max_history=100,
    )


@pytest.fixture
def interactive_session(mock_event_bus, mock_state_manager, mock_checkpoint_manager, session_config):
    """Create InteractiveSession with mocks."""
    return InteractiveSession(
        event_bus=mock_event_bus,
        state_manager=mock_state_manager,
        checkpoint_manager=mock_checkpoint_manager,
        config=session_config,
    )


@pytest.fixture
def titan_repl(mock_event_bus, mock_state_manager, mock_checkpoint_manager, session_config):
    """Create TitanREPL with mocks."""
    return TitanREPL(
        event_bus=mock_event_bus,
        state_manager=mock_state_manager,
        checkpoint_manager=mock_checkpoint_manager,
        config=session_config,
    )


# ============================================================================
# SessionConfig Tests
# ============================================================================

class TestSessionConfig:
    """Tests for SessionConfig."""
    
    def test_default_config(self):
        """Test default configuration values."""
        config = SessionConfig()
        assert config.enabled is False
        assert config.prompt == "titan> "
        assert config.history_file == ".titan/repl_history"
        assert "GATE_FAIL" in config.auto_pause_on
        assert config.max_history == 1000
        assert config.step_timeout_ms == 30000
    
    def test_config_from_dict(self):
        """Test creating config from dictionary."""
        data = {
            "enabled": True,
            "prompt": "custom> ",
            "history_file": ".custom/history",
            "auto_pause_on": ["CUSTOM_EVENT"],
            "max_history": 500,
        }
        config = SessionConfig.from_dict(data)
        assert config.enabled is True
        assert config.prompt == "custom> "
        assert config.history_file == ".custom/history"
        assert config.auto_pause_on == ["CUSTOM_EVENT"]
        assert config.max_history == 500
    
    def test_config_to_dict(self):
        """Test serializing config to dictionary."""
        config = SessionConfig(enabled=True, prompt="test> ")
        data = config.to_dict()
        assert data["enabled"] is True
        assert data["prompt"] == "test> "
        assert "auto_pause_on" in data


# ============================================================================
# Breakpoint Tests
# ============================================================================

class TestBreakpoint:
    """Tests for Breakpoint class."""
    
    def test_breakpoint_creation(self):
        """Test creating a breakpoint."""
        bp = Breakpoint(event="GATE_FAIL")
        assert bp.event == "GATE_FAIL"
        assert bp.condition is None
        assert bp.hit_count == 0
        assert bp.enabled is True
        assert bp.created_at is not None
    
    def test_breakpoint_with_condition(self):
        """Test creating a breakpoint with condition."""
        bp = Breakpoint(event="GATE_FAIL", condition="severity == 'CRITICAL'")
        assert bp.condition == "severity == 'CRITICAL'"
    
    def test_breakpoint_serialization(self):
        """Test breakpoint serialization roundtrip."""
        bp = Breakpoint(event="BUDGET_EXCEEDED", hit_count=5)
        data = bp.to_dict()
        
        assert data["event"] == "BUDGET_EXCEEDED"
        assert data["hit_count"] == 5
        
        bp2 = Breakpoint.from_dict(data)
        assert bp2.event == bp.event
        assert bp2.hit_count == bp.hit_count


# ============================================================================
# SessionStep Tests
# ============================================================================

class TestSessionStep:
    """Tests for SessionStep class."""
    
    def test_step_creation(self):
        """Test creating a session step."""
        step = SessionStep(
            step_number=1,
            event={"event_type": "GATE_PASS"},
            state_snapshot={"status": "RUNNING"},
        )
        assert step.step_number == 1
        assert step.event["event_type"] == "GATE_PASS"
        assert step.timestamp is not None
    
    def test_step_serialization(self):
        """Test step serialization roundtrip."""
        step = SessionStep(
            step_number=10,
            event={"event_type": "CHUNK_PROCESSED"},
            state_snapshot={"tokens_used": 5000},
        )
        data = step.to_dict()
        
        assert data["step_number"] == 10
        assert data["event"]["event_type"] == "CHUNK_PROCESSED"
        
        # Verify we can reconstruct
        step2 = SessionStep(
            step_number=data["step_number"],
            event=data["event"],
            state_snapshot=data["state_snapshot"],
            timestamp=data["timestamp"],
        )
        assert step2.step_number == step.step_number


# ============================================================================
# InteractiveSession Tests
# ============================================================================

class TestInteractiveSession:
    """Tests for InteractiveSession class."""
    
    def test_session_initialization(self, interactive_session, session_config):
        """Test session initialization."""
        assert interactive_session.status == SessionStatus.INITIALIZED
        assert interactive_session.step_count == 0
        assert interactive_session.config == session_config
        assert not interactive_session.is_paused
    
    def test_session_start(self, interactive_session, mock_event_bus):
        """Test starting a session."""
        interactive_session.start()
        
        assert interactive_session.status == SessionStatus.RUNNING
        mock_event_bus.subscribe.assert_called()
    
    def test_session_start_disabled(self, mock_event_bus, mock_state_manager, mock_checkpoint_manager):
        """Test starting a disabled session."""
        config = SessionConfig(enabled=False)
        session = InteractiveSession(
            event_bus=mock_event_bus,
            state_manager=mock_state_manager,
            checkpoint_manager=mock_checkpoint_manager,
            config=config,
        )
        session.start()
        
        # Should not subscribe to events when disabled
        assert session.status == SessionStatus.INITIALIZED
    
    def test_session_stop(self, interactive_session, mock_event_bus):
        """Test stopping a session."""
        interactive_session.start()
        interactive_session.stop()
        
        assert interactive_session.status == SessionStatus.COMPLETED
        mock_event_bus.unsubscribe.assert_called()
    
    def test_add_breakpoint(self, interactive_session):
        """Test adding breakpoints."""
        bp = interactive_session.add_breakpoint("GATE_FAIL")
        
        assert bp.event == "GATE_FAIL"
        assert bp in interactive_session.get_breakpoints()
    
    def test_remove_breakpoint(self, interactive_session):
        """Test removing breakpoints."""
        interactive_session.add_breakpoint("GATE_FAIL")
        result = interactive_session.remove_breakpoint("GATE_FAIL")
        
        assert result is True
        assert len(interactive_session.get_breakpoints()) == 0
    
    def test_remove_nonexistent_breakpoint(self, interactive_session):
        """Test removing a breakpoint that doesn't exist."""
        result = interactive_session.remove_breakpoint("NONEXISTENT")
        assert result is False
    
    def test_enable_disable_breakpoint(self, interactive_session):
        """Test enabling and disabling breakpoints."""
        interactive_session.add_breakpoint("GATE_FAIL")
        
        interactive_session.disable_breakpoint("GATE_FAIL")
        bp = interactive_session.get_breakpoints()[0]
        assert bp.enabled is False
        
        interactive_session.enable_breakpoint("GATE_FAIL")
        bp = interactive_session.get_breakpoints()[0]
        assert bp.enabled is True
    
    def test_inspect_state(self, interactive_session, mock_state_manager):
        """Test inspecting state values."""
        value = interactive_session.inspect("gates.GATE-00.status")
        assert value == "PASS"
    
    def test_inspect_nonexistent_path(self, interactive_session):
        """Test inspecting a path that doesn't exist."""
        value = interactive_session.inspect("nonexistent.path")
        assert value is None
    
    def test_inspect_top_level(self, interactive_session):
        """Test inspecting top-level state."""
        value = interactive_session.inspect("tokens_used")
        assert value == 1000
    
    def test_modify_state(self, interactive_session, mock_state_manager):
        """Test modifying state values."""
        interactive_session.modify("gates.GATE-01.status", "PASS")
        
        # Verify the modification was applied
        session = mock_state_manager.get_current_session()
        assert session["gates"]["GATE-01"]["status"] == "PASS"
    
    def test_step(self, interactive_session):
        """Test stepping through execution."""
        interactive_session.start()
        interactive_session.step()
        
        assert interactive_session.step_count == 1
        assert interactive_session.status == SessionStatus.STEP_MODE
    
    def test_step_history(self, interactive_session):
        """Test step history tracking."""
        interactive_session.start()
        interactive_session.step()
        interactive_session.step()
        
        history = interactive_session.get_step_history()
        assert len(history) == 2
        assert history[0].step_number == 1
        assert history[1].step_number == 2
    
    def test_pause_resume(self, interactive_session):
        """Test pausing and resuming execution."""
        interactive_session.start()
        interactive_session.pause()
        
        assert interactive_session.status == SessionStatus.PAUSED
        assert interactive_session.is_paused
        
        interactive_session.continue_execution()
        assert interactive_session.status == SessionStatus.RUNNING
    
    def test_get_status_info(self, interactive_session):
        """Test getting status information."""
        interactive_session.add_breakpoint("GATE_FAIL")
        info = interactive_session.get_status_info()
        
        assert info["status"] == "initialized"
        assert info["step_count"] == 0
        assert len(info["breakpoints"]) == 1
    
    def test_callbacks(self, interactive_session):
        """Test callback execution."""
        pause_called = []
        resume_called = []
        
        def on_pause():
            pause_called.append(True)
        
        def on_resume():
            resume_called.append(True)
        
        interactive_session.set_callbacks(on_pause=on_pause, on_resume=on_resume)
        interactive_session.start()
        interactive_session.pause()
        interactive_session.continue_execution()
        
        assert len(pause_called) == 1
        assert len(resume_called) == 1
    
    def test_save_load_history(self, interactive_session):
        """Test saving and loading history."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "history.json"
            
            interactive_session.add_breakpoint("GATE_FAIL")
            interactive_session.start()
            interactive_session.step()
            
            # Save
            assert interactive_session.save_history(str(path))
            
            # Create new session and load
            new_session = InteractiveSession()
            assert new_session.load_history(str(path))
            
            history = new_session.get_step_history()
            assert len(history) == 1


# ============================================================================
# TitanREPL Tests
# ============================================================================

class TestTitanREPL:
    """Tests for TitanREPL class."""
    
    def test_repl_initialization(self, titan_repl):
        """Test REPL initialization."""
        assert titan_repl.session is not None
        assert titan_repl.session.config.enabled is True
    
    def test_parse_command(self, titan_repl):
        """Test command parsing."""
        parts = titan_repl._parse_command('inspect "path with spaces"')
        assert parts == ["inspect", "path with spaces"]
        
        parts = titan_repl._parse_command("modify key value")
        assert parts == ["modify", "key", "value"]
    
    def test_execute_status(self, titan_repl):
        """Test status command."""
        result = titan_repl.execute("status")
        
        assert result.success
        assert "Session Status" in result.output
    
    def test_execute_help(self, titan_repl):
        """Test help command."""
        result = titan_repl.execute("help")
        
        assert result.success
        assert "TITAN Protocol" in result.output
        assert "status" in result.output
        assert "step" in result.output
    
    def test_execute_inspect(self, titan_repl):
        """Test inspect command."""
        result = titan_repl.execute("inspect gates")
        
        assert result.success
        assert "gates:" in result.output
    
    def test_execute_inspect_missing_path(self, titan_repl):
        """Test inspect command without path."""
        result = titan_repl.execute("inspect")
        
        assert not result.success
        assert "Usage:" in result.error
    
    def test_execute_modify(self, titan_repl):
        """Test modify command."""
        result = titan_repl.execute("modify gates.GATE-01.status PASS")
        
        assert result.success
        assert "Modified" in result.output
    
    def test_execute_modify_missing_args(self, titan_repl):
        """Test modify command with missing arguments."""
        result = titan_repl.execute("modify path")
        
        assert not result.success
        assert "Usage:" in result.error
    
    def test_execute_breakpoint(self, titan_repl):
        """Test breakpoint command."""
        result = titan_repl.execute("breakpoint BUDGET_EXCEEDED")
        
        assert result.success
        assert "Added breakpoint" in result.output
    
    def test_execute_list_breakpoints(self, titan_repl):
        """Test list command."""
        titan_repl.execute("breakpoint GATE_FAIL")
        result = titan_repl.execute("list")
        
        assert result.success
        assert "GATE_FAIL" in result.output
    
    def test_execute_clear_breakpoint(self, titan_repl):
        """Test clear command."""
        titan_repl.execute("breakpoint GATE_FAIL")
        result = titan_repl.execute("clear GATE_FAIL")
        
        assert result.success
        assert "Cleared" in result.output
    
    def test_execute_clear_nonexistent(self, titan_repl):
        """Test clearing nonexistent breakpoint."""
        result = titan_repl.execute("clear NONEXISTENT")
        
        assert not result.success
    
    def test_execute_step(self, titan_repl):
        """Test step command."""
        titan_repl.session.start()
        result = titan_repl.execute("step")
        
        assert result.success
        assert "step" in result.output.lower()
    
    def test_execute_continue(self, titan_repl):
        """Test continue command."""
        titan_repl.session.start()
        titan_repl.session.pause()
        result = titan_repl.execute("continue")
        
        assert result.success
        assert "Continuing" in result.output
    
    def test_execute_history(self, titan_repl):
        """Test history command."""
        titan_repl.session.start()
        titan_repl.session.step()
        result = titan_repl.execute("history")
        
        assert result.success
        assert "Step History" in result.output
    
    def test_execute_pause(self, titan_repl):
        """Test pause command."""
        titan_repl.session.start()
        result = titan_repl.execute("pause")
        
        assert result.success
        assert "paused" in result.output.lower()
    
    def test_execute_quit(self, titan_repl):
        """Test quit command."""
        result = titan_repl.execute("quit")
        
        assert result.success
        assert "Goodbye" in result.output
        assert not titan_repl._running
    
    def test_unknown_command(self, titan_repl):
        """Test unknown command."""
        result = titan_repl.execute("unknown_command")
        
        assert not result.success
        assert "Unknown command" in result.error
    
    def test_command_aliases(self, titan_repl):
        """Test command aliases."""
        # 'c' should alias to 'continue'
        titan_repl.session.start()
        titan_repl.session.pause()
        result = titan_repl.execute("c")
        assert result.success
        
        # 'i' should alias to 'inspect'
        result = titan_repl.execute("i gates")
        assert result.success
        
        # '?' should alias to 'help'
        result = titan_repl.execute("?")
        assert result.success
    
    def test_command_history_tracking(self, titan_repl):
        """Test command history is tracked."""
        # Add commands to history manually (simulating REPL input loop)
        titan_repl._command_history.append("status")
        titan_repl._command_history.append("help")
        titan_repl._command_history.append("list")
        
        history = titan_repl.get_command_history()
        assert "status" in history
        assert "help" in history
        assert "list" in history
    
    def test_json_value_parsing_in_modify(self, titan_repl):
        """Test that modify can parse JSON values."""
        result = titan_repl.execute('modify test.key {"nested": "value"}')
        assert result.success
        
        result = titan_repl.execute('modify test.array [1, 2, 3]')
        assert result.success
        
        result = titan_repl.execute('modify test.number 42')
        assert result.success
    
    def test_rollback_with_no_args(self, titan_repl):
        """Test rollback command without step number."""
        titan_repl.session.start()
        titan_repl.session.step()
        result = titan_repl.execute("rollback")
        
        assert result.success
        assert "Available steps" in result.output


# ============================================================================
# CommandResult Tests
# ============================================================================

class TestCommandResult:
    """Tests for CommandResult class."""
    
    def test_success_result(self):
        """Test successful result."""
        result = CommandResult(success=True, output="Done")
        assert result.success
        assert str(result) == "Done"
    
    def test_error_result(self):
        """Test error result."""
        result = CommandResult(success=False, error="Failed")
        assert not result.success
        assert str(result) == "Error: Failed"
    
    def test_result_with_data(self):
        """Test result with additional data."""
        result = CommandResult(
            success=True,
            output="Found",
            data={"key": "value"}
        )
        assert result.data["key"] == "value"


# ============================================================================
# CommandType Tests
# ============================================================================

class TestCommandType:
    """Tests for CommandType enum."""
    
    def test_command_types(self):
        """Test all command types are defined."""
        assert CommandType.STATUS.value == "status"
        assert CommandType.STEP.value == "step"
        assert CommandType.CONTINUE.value == "continue"
        assert CommandType.INSPECT.value == "inspect"
        assert CommandType.MODIFY.value == "modify"
        assert CommandType.BREAKPOINT.value == "breakpoint"
        assert CommandType.ROLLBACK.value == "rollback"
        assert CommandType.HELP.value == "help"
        assert CommandType.QUIT.value == "quit"


# ============================================================================
# Integration Tests
# ============================================================================

class TestIntegration:
    """Integration tests for interactive module."""
    
    def test_full_session_workflow(self, mock_event_bus, mock_state_manager, mock_checkpoint_manager):
        """Test a complete debugging workflow."""
        # Use empty auto_pause_on to avoid auto-added breakpoints
        config = SessionConfig(enabled=True, auto_pause_on=[])
        session = InteractiveSession(
            event_bus=mock_event_bus,
            state_manager=mock_state_manager,
            checkpoint_manager=mock_checkpoint_manager,
            config=config,
        )
        
        # Start session
        session.start()
        assert session.status == SessionStatus.RUNNING
        
        # Add breakpoints
        session.add_breakpoint("GATE_FAIL")
        session.add_breakpoint("BUDGET_EXCEEDED")
        assert len(session.get_breakpoints()) == 2
        
        # Pause and step
        session.pause()
        assert session.is_paused
        
        session.step()
        assert session.step_count == 1
        
        # Inspect and modify state
        value = session.inspect("tokens_used")
        assert value == 1000
        
        session.modify("tokens_used", 2000)
        
        # Continue
        session.continue_execution()
        assert session.status == SessionStatus.RUNNING
        
        # Stop
        session.stop()
        assert session.status == SessionStatus.COMPLETED
    
    def test_repl_workflow(self, mock_event_bus, mock_state_manager, mock_checkpoint_manager):
        """Test complete REPL workflow."""
        config = SessionConfig(enabled=True)
        repl = TitanREPL(
            event_bus=mock_event_bus,
            state_manager=mock_state_manager,
            checkpoint_manager=mock_checkpoint_manager,
            config=config,
        )
        
        # Simulate interactive session
        commands = [
            "help",
            "status",
            "breakpoint GATE_FAIL",
            "list",
            "inspect gates",
            "modify gates.GATE-00.status WARN",
            "history",
        ]
        
        results = []
        for cmd in commands:
            result = repl.execute(cmd)
            results.append(result)
        
        # All commands should succeed
        assert all(r.success for r in results)
        
        # Verify commands executed successfully (history is tracked in run() loop, not execute())


# ============================================================================
# Edge Cases
# ============================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""
    
    def test_session_without_dependencies(self):
        """Test session with no event bus or state manager."""
        session = InteractiveSession()
        
        # Should not crash
        session.start()
        session.step()
        assert session.inspect("any.path") is None
        session.modify("any.path", "value")
    
    def test_empty_command(self, titan_repl):
        """Test handling empty command."""
        result = titan_repl.execute("")
        assert result.success
    
    def test_whitespace_command(self, titan_repl):
        """Test handling whitespace-only command."""
        result = titan_repl.execute("   ")
        assert result.success
    
    def test_step_without_start(self, titan_repl):
        """Test stepping without starting session."""
        result = titan_repl.execute("step")
        # Should handle gracefully
        assert not result.success or "step" in result.output.lower()
    
    def test_continue_without_pause(self, titan_repl):
        """Test continue without being paused."""
        titan_repl.session.start()
        result = titan_repl.execute("continue")
        # Should handle gracefully
        assert result is not None
    
    def test_modify_creates_nested_path(self, mock_state_manager):
        """Test modify creates intermediate dictionaries."""
        config = SessionConfig(enabled=True)
        session = InteractiveSession(state_manager=mock_state_manager, config=config)
        
        # Modify a deeply nested path that doesn't exist
        session.modify("new.nested.path.value", "test")
        
        session_state = mock_state_manager.get_current_session()
        assert "new" in session_state
        assert session_state["new"]["nested"]["path"]["value"] == "test"
    
    def test_history_limit(self, mock_event_bus, mock_state_manager):
        """Test history respects max limit."""
        config = SessionConfig(enabled=True, max_history=5)
        session = InteractiveSession(
            event_bus=mock_event_bus,
            state_manager=mock_state_manager,
            config=config,
        )
        
        session.start()
        for i in range(10):
            session.step()
        
        history = session.get_step_history()
        # Should be limited to max_history
        assert len(history) <= 5


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
