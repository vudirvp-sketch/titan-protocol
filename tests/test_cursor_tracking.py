"""
Tests for ITEM-STOR-05: Cursor Hash for Drift Detection.

Tests cursor tracking with hash computation and drift detection.

Author: TITAN FUSE Team
Version: 3.3.0
"""

import pytest
import hashlib
import json
import tempfile
from pathlib import Path

from src.state.cursor import (
    CursorTracker,
    CursorState,
    DriftResult,
    compute_state_hash,
    verify_state_integrity
)
from src.state.checkpoint_serialization import (
    add_cursor_hash_to_checkpoint,
    verify_checkpoint_cursor_hash,
    deserialize_checkpoint_with_verification
)
from src.events.event_bus import EventBus, EventSeverity


class TestCursorState:
    """Tests for CursorState dataclass."""
    
    def test_cursor_state_creation(self):
        """Test basic CursorState creation."""
        state = CursorState(
            cursor_hash="abc123",
            last_patch_hash="def456",
            patch_count=5
        )
        
        assert state.cursor_hash == "abc123"
        assert state.last_patch_hash == "def456"
        assert state.patch_count == 5
        assert state.current_line == 0
        assert state.current_chunk is None
    
    def test_cursor_state_to_dict(self):
        """Test CursorState serialization."""
        state = CursorState(
            cursor_hash="abc123",
            patch_count=3,
            current_line=42
        )
        
        data = state.to_dict()
        
        assert data["cursor_hash"] == "abc123"
        assert data["patch_count"] == 3
        assert data["current_line"] == 42
        assert "timestamp" in data
    
    def test_cursor_state_from_dict(self):
        """Test CursorState deserialization."""
        data = {
            "cursor_hash": "xyz789",
            "last_patch_hash": "prev123",
            "patch_count": 10,
            "current_line": 100,
            "current_chunk": "chunk-5"
        }
        
        state = CursorState.from_dict(data)
        
        assert state.cursor_hash == "xyz789"
        assert state.last_patch_hash == "prev123"
        assert state.patch_count == 10
        assert state.current_line == 100
        assert state.current_chunk == "chunk-5"


class TestDriftResult:
    """Tests for DriftResult dataclass."""
    
    def test_drift_result_valid(self):
        """Test valid DriftResult."""
        result = DriftResult(
            valid=True,
            expected_hash="abc123",
            actual_hash="abc123"
        )
        
        assert result.valid is True
        assert result.gap_tag is None
    
    def test_drift_result_invalid(self):
        """Test invalid DriftResult."""
        result = DriftResult(
            valid=False,
            expected_hash="abc123",
            actual_hash="xyz789",
            gap_tag="[gap: cursor_drift_detected]"
        )
        
        assert result.valid is False
        assert result.gap_tag == "[gap: cursor_drift_detected]"
    
    def test_drift_result_to_dict(self):
        """Test DriftResult serialization."""
        result = DriftResult(
            valid=False,
            expected_hash="abc",
            actual_hash="xyz",
            gap_tag="[gap: test]"
        )
        
        data = result.to_dict()
        
        assert data["valid"] is False
        assert data["expected_hash"] == "abc"
        assert data["actual_hash"] == "xyz"
        assert data["gap_tag"] == "[gap: test]"


class TestCursorTracker:
    """Tests for CursorTracker class."""
    
    def test_initialization(self):
        """Test CursorTracker initialization."""
        tracker = CursorTracker()
        
        assert tracker.cursor_hash is None
        assert tracker.last_patch_hash is None
        assert len(tracker.get_patch_history()) == 0
    
    def test_compute_hash(self):
        """Test hash computation from state."""
        tracker = CursorTracker()
        
        state = {"key": "value", "number": 42}
        hash1 = tracker.compute_hash(state)
        
        assert hash1 is not None
        assert len(hash1) == 32
        assert tracker.cursor_hash == hash1
    
    def test_compute_hash_deterministic(self):
        """Test that hash computation is deterministic."""
        state = {"a": 1, "b": 2, "c": 3}
        
        hash1 = compute_state_hash(state)
        hash2 = compute_state_hash(state)
        
        assert hash1 == hash2
    
    def test_compute_hash_different_states(self):
        """Test that different states produce different hashes."""
        state1 = {"key": "value1"}
        state2 = {"key": "value2"}
        
        hash1 = compute_state_hash(state1)
        hash2 = compute_state_hash(state2)
        
        assert hash1 != hash2
    
    def test_update_cursor_hash(self):
        """Test cursor hash update with patch."""
        tracker = CursorTracker()
        
        hash1 = tracker.update_cursor_hash("first patch")
        hash2 = tracker.update_cursor_hash("second patch")
        
        assert hash1 != hash2
        assert len(tracker.get_patch_history()) == 2
        assert tracker.last_patch_hash == hash2
    
    def test_update_cursor_with_operation(self):
        """Test cursor update with operation and changes."""
        tracker = CursorTracker()
        
        new_hash = tracker.update_cursor(
            operation="PATCH_APPLIED",
            changes={"file": "test.py", "lines": 5}
        )
        
        assert new_hash is not None
        assert len(tracker.get_operation_history()) == 1
        
        history = tracker.get_operation_history()
        assert history[0]["operation"] == "PATCH_APPLIED"
    
    def test_verify_cursor_valid(self):
        """Test cursor verification with matching hash."""
        tracker = CursorTracker()
        
        tracker.update_cursor_hash("test patch")
        expected_hash = tracker.cursor_hash
        
        result = tracker.verify_cursor(expected_hash)
        
        assert result.valid is True
        assert result.actual_hash == expected_hash
    
    def test_verify_cursor_invalid(self):
        """Test cursor verification with mismatched hash."""
        tracker = CursorTracker()
        
        tracker.update_cursor_hash("test patch")
        result = tracker.verify_cursor("wrong_hash")
        
        assert result.valid is False
        assert result.gap_tag == "[gap: cursor_drift_detected]"
    
    def test_verify_cursor_emits_event(self):
        """Test that cursor verification emits CURSOR_DRIFT event."""
        event_bus = EventBus()
        tracker = CursorTracker(event_bus=event_bus)
        
        events_received = []
        
        def capture_event(event):
            events_received.append(event)
        
        event_bus.subscribe("CURSOR_DRIFT", capture_event)
        
        tracker.update_cursor_hash("test")
        result = tracker.verify_cursor("wrong_hash", emit_event=True)
        
        assert result.valid is False
        assert len(events_received) == 1
        assert events_received[0].event_type == "CURSOR_DRIFT"
    
    def test_update_position(self):
        """Test position update."""
        tracker = CursorTracker()
        
        tracker.update_position(line=100, chunk="chunk-5", offset=10)
        
        state = tracker.get_state()
        
        assert state["current_line"] == 100
        assert state["current_chunk"] == "chunk-5"
        assert state["offset_delta"] == 10
    
    def test_get_state(self):
        """Test getting cursor state."""
        tracker = CursorTracker()
        
        tracker.update_cursor_hash("patch")
        tracker.update_position(line=50)
        
        state = tracker.get_state()
        
        assert "cursor_hash" in state
        assert state["current_line"] == 50
        assert state["patch_count"] == 1
    
    def test_restore_state(self):
        """Test restoring cursor state."""
        tracker1 = CursorTracker()
        tracker1.update_cursor_hash("patch")
        tracker1.update_position(line=100, chunk="chunk-10")
        
        state = tracker1.get_state()
        
        tracker2 = CursorTracker()
        tracker2.restore_state(state)
        
        assert tracker2.cursor_hash == tracker1.cursor_hash
        assert tracker2._current_line == 100
        assert tracker2._current_chunk == "chunk-10"
    
    def test_reset(self):
        """Test cursor tracker reset."""
        tracker = CursorTracker()
        
        tracker.update_cursor_hash("patch")
        tracker.update_position(line=50)
        tracker.reset()
        
        assert tracker.cursor_hash is None
        assert tracker.last_patch_hash is None
        assert len(tracker.get_patch_history()) == 0
    
    def test_validate_cursor_on_resume(self):
        """Test cursor validation on resume."""
        tracker = CursorTracker()
        
        # Simulate checkpoint state
        checkpoint_state = {"session_id": "test", "phase": 1}
        checkpoint_hash = tracker.compute_hash(checkpoint_state)
        
        # Simulate resume with same state
        result = tracker.validate_cursor_on_resume(checkpoint_hash, checkpoint_state)
        
        assert result.valid is True
    
    def test_validate_cursor_on_resume_drift(self):
        """Test cursor validation detects drift on resume."""
        tracker = CursorTracker()
        
        # Simulate checkpoint state
        checkpoint_state = {"session_id": "test", "phase": 1}
        checkpoint_hash = tracker.compute_hash(checkpoint_state)
        
        # Simulate modified state
        modified_state = {"session_id": "test", "phase": 2}
        result = tracker.validate_cursor_on_resume(checkpoint_hash, modified_state)
        
        assert result.valid is False
        assert result.gap_tag == "[gap: external_modification_during_wait]"


class TestComputeStateHash:
    """Tests for compute_state_hash function."""
    
    def test_hash_consistency(self):
        """Test that same state produces same hash."""
        state = {"a": 1, "b": "test", "c": [1, 2, 3]}
        
        hash1 = compute_state_hash(state)
        hash2 = compute_state_hash(state)
        
        assert hash1 == hash2
    
    def test_key_order_independence(self):
        """Test that key order doesn't affect hash."""
        state1 = {"a": 1, "b": 2}
        state2 = {"b": 2, "a": 1}
        
        hash1 = compute_state_hash(state1)
        hash2 = compute_state_hash(state2)
        
        assert hash1 == hash2
    
    def test_value_change_affects_hash(self):
        """Test that value changes affect hash."""
        state1 = {"key": "value1"}
        state2 = {"key": "value2"}
        
        hash1 = compute_state_hash(state1)
        hash2 = compute_state_hash(state2)
        
        assert hash1 != hash2


class TestVerifyStateIntegrity:
    """Tests for verify_state_integrity function."""
    
    def test_valid_integrity(self):
        """Test integrity verification with valid hash."""
        state = {"key": "value"}
        expected_hash = compute_state_hash(state)
        
        result = verify_state_integrity(state, expected_hash)
        
        assert result.valid is True
    
    def test_invalid_integrity(self):
        """Test integrity verification with invalid hash."""
        state = {"key": "value"}
        
        result = verify_state_integrity(state, "wrong_hash")
        
        assert result.valid is False
        assert result.gap_tag == "[gap: cursor_drift_detected]"


class TestCheckpointCursorHash:
    """Tests for checkpoint cursor hash integration."""
    
    def test_add_cursor_hash_to_checkpoint(self):
        """Test adding cursor hash to checkpoint."""
        checkpoint = {
            "session_id": "test-123",
            "phase": 1,
            "tokens_used": 100
        }
        
        result = add_cursor_hash_to_checkpoint(checkpoint)
        
        assert "cursor_hash" in result
        assert len(result["cursor_hash"]) == 32
    
    def test_verify_checkpoint_cursor_hash_valid(self):
        """Test verifying valid checkpoint cursor hash."""
        checkpoint = {
            "session_id": "test-123",
            "phase": 1
        }
        
        checkpoint_with_hash = add_cursor_hash_to_checkpoint(checkpoint)
        result = verify_checkpoint_cursor_hash(checkpoint_with_hash)
        
        assert result["valid"] is True
    
    def test_verify_checkpoint_cursor_hash_invalid(self):
        """Test detecting tampered checkpoint."""
        checkpoint = {
            "session_id": "test-123",
            "phase": 1,
            "cursor_hash": "fakehash12345678901234567890"
        }
        
        result = verify_checkpoint_cursor_hash(checkpoint)
        
        assert result["valid"] is False
        assert "error" in result
    
    def test_verify_checkpoint_without_cursor_hash(self):
        """Test verifying pre-3.3.0 checkpoint without cursor hash."""
        checkpoint = {
            "session_id": "test-123",
            "phase": 1
        }
        
        result = verify_checkpoint_cursor_hash(checkpoint)
        
        assert result["valid"] is True
        assert "warning" in result
    
    def test_deserialize_with_verification(self):
        """Test deserialization with cursor hash verification."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create checkpoint with cursor hash
            checkpoint = {
                "session_id": "test-123",
                "phase": 1
            }
            checkpoint_with_hash = add_cursor_hash_to_checkpoint(checkpoint)
            
            # Save to file
            checkpoint_path = Path(tmpdir) / "checkpoint.json"
            with open(checkpoint_path, 'w') as f:
                json.dump(checkpoint_with_hash, f)
            
            # Deserialize with verification
            data, result = deserialize_checkpoint_with_verification(path=checkpoint_path)
            
            assert result.success is True
            assert data["session_id"] == "test-123"
    
    def test_deserialize_detects_tampering(self):
        """Test that deserialization detects tampering."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create checkpoint with cursor hash
            checkpoint = {
                "session_id": "test-123",
                "phase": 1,
                "cursor_hash": "fakehash12345678901234567890"  # Wrong hash
            }
            
            # Save to file
            checkpoint_path = Path(tmpdir) / "checkpoint.json"
            with open(checkpoint_path, 'w') as f:
                json.dump(checkpoint, f)
            
            # Deserialize with verification
            data, result = deserialize_checkpoint_with_verification(path=checkpoint_path)
            
            assert result.success is False
            assert "cursor_hash" in result.error.lower()


class TestEventBusIntegration:
    """Tests for EventBus integration with cursor tracking."""
    
    def test_cursor_drift_event_severity(self):
        """Test that CURSOR_DRIFT events have WARN severity."""
        event_bus = EventBus()
        tracker = CursorTracker(event_bus=event_bus)
        
        events_received = []
        
        def capture_event(event):
            events_received.append(event)
        
        event_bus.subscribe("CURSOR_DRIFT", capture_event)
        
        tracker.update_cursor_hash("test")
        tracker.verify_cursor("wrong_hash", emit_event=True)
        
        assert len(events_received) == 1
        assert events_received[0].severity == EventSeverity.WARN
    
    def test_severity_subscription_receives_drift(self):
        """Test that severity subscription receives drift events."""
        event_bus = EventBus()
        tracker = CursorTracker(event_bus=event_bus)
        
        warn_events = []
        
        def capture_warn(event):
            warn_events.append(event)
        
        event_bus.subscribe_severity(EventSeverity.WARN, capture_warn)
        
        tracker.update_cursor_hash("test")
        tracker.verify_cursor("wrong_hash", emit_event=True)
        
        assert len(warn_events) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
