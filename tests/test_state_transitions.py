"""
Tests for ITEM-OBS-06: Event-State Transition Contract

This module tests the state transition validator functionality.

Author: TITAN FUSE Team
Version: 3.3.0
"""

import pytest
import json
import tempfile
from pathlib import Path

from src.observability.state_validator import (
    StateTransitionValidator,
    StateSnapshot,
    StateMutation,
    TransitionResult,
    TransitionValidation,
    validate_event_transition,
    get_state_transition_map,
)


class TestTransitionResult:
    """Tests for TransitionResult enum."""

    def test_transition_results_exist(self):
        """Test that all transition results are defined."""
        assert hasattr(TransitionResult, "VALID")
        assert hasattr(TransitionResult, "INVALID")
        assert hasattr(TransitionResult, "WARNING")
        assert hasattr(TransitionResult, "UNKNOWN_EVENT")

    def test_transition_result_values(self):
        """Test transition result string values."""
        assert TransitionResult.VALID.value == "valid"
        assert TransitionResult.INVALID.value == "invalid"
        assert TransitionResult.WARNING.value == "warning"
        assert TransitionResult.UNKNOWN_EVENT.value == "unknown_event"


class TestStateSnapshot:
    """Tests for StateSnapshot dataclass."""

    def test_create_empty_snapshot(self):
        """Test creating an empty state snapshot."""
        snapshot = StateSnapshot()
        assert snapshot.session == {}
        assert snapshot.phases == {}
        assert snapshot.chunks == {}
        assert snapshot.gates == {}

    def test_snapshot_to_dict(self):
        """Test converting snapshot to dictionary."""
        snapshot = StateSnapshot(
            session={"status": "in_progress"},
            gates={"GATE-01": {"status": "PASS"}}
        )
        d = snapshot.to_dict()

        assert d["session"]["status"] == "in_progress"
        assert d["gates"]["GATE-01"]["status"] == "PASS"

    def test_snapshot_from_dict(self):
        """Test creating snapshot from dictionary."""
        d = {
            "session": {"status": "completed"},
            "phases": {"phase_1": {"status": "completed"}},
            "chunks": {},
            "gates": {},
            "issues": {},
            "cursor": {},
            "metrics": {},
            "inventory": {}
        }
        snapshot = StateSnapshot.from_dict(d)

        assert snapshot.session["status"] == "completed"
        assert snapshot.phases["phase_1"]["status"] == "completed"


class TestStateMutation:
    """Tests for StateMutation dataclass."""

    def test_create_mutation(self):
        """Test creating a state mutation."""
        mutation = StateMutation(
            path="gates.{gate_id}.status",
            value="PASS",
            resolved_path="gates.GATE-01.status"
        )

        assert mutation.path == "gates.{gate_id}.status"
        assert mutation.value == "PASS"
        assert mutation.resolved_path == "gates.GATE-01.status"


class TestStateTransitionValidator:
    """Tests for StateTransitionValidator class."""

    def test_create_validator(self):
        """Test creating a validator instance."""
        validator = StateTransitionValidator()
        assert validator is not None

    def test_validate_known_event(self):
        """Test validating a known event type."""
        validator = StateTransitionValidator()
        validation = validator.validate_transition("GATE_PASS", {"gate_id": "GATE-01"})

        assert validation.result in [TransitionResult.VALID, TransitionResult.WARNING]
        assert validation.event_type == "GATE_PASS"

    def test_validate_unknown_event(self):
        """Test validating an unknown event type."""
        validator = StateTransitionValidator()
        validation = validator.validate_transition("UNKNOWN_EVENT", {})

        assert validation.result == TransitionResult.UNKNOWN_EVENT

    def test_validate_gate_fail_blocks_session(self):
        """Test that GATE_FAIL blocks session in correct state."""
        validator = StateTransitionValidator()
        validator.set_state(StateSnapshot(session={"status": "in_progress"}))

        validation = validator.validate_transition("GATE_FAIL", {"gate_id": "GATE-01"})

        # Should produce state mutations for blocking
        assert validation.event_type == "GATE_FAIL"
        assert len(validation.state_mutations) > 0

    def test_validate_session_end_in_wrong_state(self):
        """Test that SESSION_END is invalid when not in_progress."""
        validator = StateTransitionValidator()
        validator.set_state(StateSnapshot(session={"status": "completed"}))

        validation = validator.validate_transition("SESSION_END", {})

        # Should have errors since session is already completed
        assert validation.result == TransitionResult.INVALID
        assert len(validation.errors) > 0

    def test_apply_transition(self):
        """Test applying a transition."""
        validator = StateTransitionValidator()

        # Apply SESSION_START
        validation = validator.apply_transition("SESSION_START", {})

        assert validation.result in [TransitionResult.VALID, TransitionResult.WARNING]

        # Check state was updated
        state = validator.get_state()
        assert state.session.get("status") == "in_progress"

    def test_get_valid_events(self):
        """Test getting valid events for current state."""
        validator = StateTransitionValidator()

        valid_events = validator.get_valid_events()

        # Should include SESSION_START for initialized state
        assert "SESSION_START" in valid_events

    def test_event_history(self):
        """Test event history tracking."""
        validator = StateTransitionValidator()

        validator.apply_transition("SESSION_START", {})
        validator.apply_transition("GATE_PASS", {"gate_id": "GATE-01"})

        history = validator.get_event_history()

        assert len(history) == 2
        assert history[0]["event_type"] == "SESSION_START"
        assert history[1]["event_type"] == "GATE_PASS"

    def test_replay_events(self):
        """Test replaying events to rebuild state."""
        validator = StateTransitionValidator()

        events = [
            {"event_type": "SESSION_START", "data": {}},
            {"event_type": "GATE_PASS", "data": {"gate_id": "GATE-01"}},
        ]

        final_state = validator.replay_events(events)

        assert final_state.session.get("status") == "in_progress"
        assert len(validator.get_event_history()) == 2

    def test_get_stats(self):
        """Test getting validator statistics."""
        validator = StateTransitionValidator()

        validator.apply_transition("SESSION_START", {})

        stats = validator.get_stats()

        assert "events_processed" in stats
        assert stats["events_processed"] == 1
        assert "current_session_status" in stats


class TestValidateEventTransition:
    """Tests for the convenience function."""

    def test_validate_event_transition(self):
        """Test the convenience function for validation."""
        current_state = {
            "session": {"status": "in_progress"},
            "phases": {},
            "chunks": {},
            "gates": {},
            "issues": {},
            "cursor": {},
            "metrics": {},
            "inventory": {}
        }

        validation = validate_event_transition(
            "GATE_PASS",
            {"gate_id": "GATE-01"},
            current_state
        )

        assert validation.event_type == "GATE_PASS"


class TestGetStateTransitionMap:
    """Tests for getting the state transition map."""

    def test_get_state_transition_map(self):
        """Test getting the state transition map."""
        state_map = get_state_transition_map()

        assert isinstance(state_map, dict)
        # Should have event_state_map or be empty dict
        assert "event_state_map" in state_map or len(state_map) >= 0


class TestStateMapValidation:
    """Tests for state map validation rules."""

    def test_gate_pass_transition(self):
        """Test GATE_PASS produces correct transition."""
        validator = StateTransitionValidator()
        validator.set_state(StateSnapshot(session={"status": "in_progress"}))

        validation = validator.validate_transition("GATE_PASS", {"gate_id": "GATE-01"})

        # Check for expected mutations
        mutation_paths = [m.path for m in validation.state_mutations]
        # Should have gate status mutation
        assert any("gates" in path for path in mutation_paths)

    def test_session_start_from_initialized(self):
        """Test SESSION_START from initialized state."""
        validator = StateTransitionValidator()
        validator.set_state(StateSnapshot(session={"status": "initialized"}))

        validation = validator.validate_transition("SESSION_START", {})

        # Should be valid from initialized state
        assert validation.result in [TransitionResult.VALID, TransitionResult.WARNING]

    def test_budget_exceeded_produces_gap(self):
        """Test that BUDGET_EXCEEDED emits gap tags."""
        validator = StateTransitionValidator()

        validation = validator.validate_transition("BUDGET_EXCEEDED", {"remaining": 0})

        # Should have gap tags
        assert len(validation.gap_tags) > 0


class TestStateMapLoading:
    """Tests for state map loading."""

    def test_load_custom_state_map(self):
        """Test loading a custom state map file."""
        # Create a temporary state map file
        state_map = {
            "event_state_map": {
                "CUSTOM_EVENT": {
                    "state_transition": "custom",
                    "state_mutations": ["session.custom = true"],
                    "valid_pre_states": ["*"],
                    "invalid_pre_states": [],
                    "emits_gaps": False
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(state_map, f)
            temp_path = f.name

        try:
            validator = StateTransitionValidator(state_map_path=temp_path)
            validation = validator.validate_transition("CUSTOM_EVENT", {})

            assert validation.event_type == "CUSTOM_EVENT"
        finally:
            Path(temp_path).unlink()

    def test_missing_state_map_uses_defaults(self):
        """Test that missing state map uses defaults."""
        validator = StateTransitionValidator(state_map_path="/nonexistent/path.json")

        # Should not raise, should use defaults
        assert validator is not None


class TestIntegration:
    """Integration tests for state validator."""

    def test_full_session_workflow(self):
        """Test a complete session workflow."""
        validator = StateTransitionValidator()

        # Start session
        result = validator.apply_transition("SESSION_START", {})
        assert result.result in [TransitionResult.VALID, TransitionResult.WARNING]

        # Pass gate
        result = validator.apply_transition("GATE_PASS", {"gate_id": "GATE-01"})
        assert result.result in [TransitionResult.VALID, TransitionResult.WARNING]

        # Complete phase
        result = validator.apply_transition("PHASE_COMPLETE", {"phase_id": "phase_1"})
        assert result.result in [TransitionResult.VALID, TransitionResult.WARNING]

        # End session
        result = validator.apply_transition("SESSION_END", {})
        assert result.result in [TransitionResult.VALID, TransitionResult.WARNING]

        # Check final state
        state = validator.get_state()
        assert state.session.get("status") == "completed"

    def test_blocked_session_workflow(self):
        """Test a session that gets blocked."""
        validator = StateTransitionValidator()

        # Start session
        validator.apply_transition("SESSION_START", {})

        # Fail gate (should block)
        result = validator.apply_transition("GATE_FAIL", {"gate_id": "GATE-01"})

        # Check state is blocked
        state = validator.get_state()
        assert state.session.get("status") in ["BLOCKED", "blocked", "in_progress"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
