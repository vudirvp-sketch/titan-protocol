"""
Tests for ITEM-ARCH-16: External State Drift Policy.

Tests drift detection and conflict resolution policies.

Author: TITAN FUSE Team
Version: 3.7.0
"""

import pytest
import hashlib
import json
import tempfile
from pathlib import Path

from src.state.drift_policy import (
    ConflictPolicy,
    DriftReport,
    DriftPolicyHandler,
    DriftDetectedError,
    MergeConflictError,
    ActionResult,
    check_state_drift
)
from src.state.cursor import (
    CursorTracker,
    compute_state_hash
)
from src.events.event_bus import EventBus, EventSeverity, EventTypes


class TestConflictPolicy:
    """Tests for ConflictPolicy enum."""

    def test_policy_values(self):
        """Test that all policy values exist."""
        assert ConflictPolicy.FAIL.value == "FAIL"
        assert ConflictPolicy.CLOBBER.value == "CLOBBER"
        assert ConflictPolicy.MERGE.value == "MERGE"
        assert ConflictPolicy.BRANCH.value == "BRANCH"

    def test_policy_count(self):
        """Test that we have exactly 4 policies."""
        assert len(ConflictPolicy) == 4


class TestDriftReport:
    """Tests for DriftReport dataclass."""

    def test_drift_report_creation(self):
        """Test basic DriftReport creation."""
        report = DriftReport(
            local_hash="abc123",
            external_hash="xyz789",
            affected_keys=["key1", "key2"]
        )

        assert report.local_hash == "abc123"
        assert report.external_hash == "xyz789"
        assert len(report.affected_keys) == 2
        assert report.resolution is None
        assert report.drift_id.startswith("drift-")

    def test_drift_report_to_dict(self):
        """Test DriftReport serialization."""
        report = DriftReport(
            local_hash="abc",
            external_hash="xyz",
            diff_summary={"key1": {"status": "conflict"}},
            affected_keys=["key1"],
            resolution="MERGED"
        )

        data = report.to_dict()

        assert data["local_hash"] == "abc"
        assert data["external_hash"] == "xyz"
        assert data["resolution"] == "MERGED"
        assert "drift_id" in data

    def test_drift_report_from_dict(self):
        """Test DriftReport deserialization."""
        data = {
            "drift_id": "drift-test123",
            "local_hash": "abc",
            "external_hash": "xyz",
            "affected_keys": ["key1"],
            "resolution": "BRANCHED"
        }

        report = DriftReport.from_dict(data)

        assert report.drift_id == "drift-test123"
        assert report.local_hash == "abc"
        assert report.resolution == "BRANCHED"


class TestActionResult:
    """Tests for ActionResult dataclass."""

    def test_action_result_success(self):
        """Test successful ActionResult."""
        result = ActionResult(
            success=True,
            policy_applied=ConflictPolicy.CLOBBER,
            message="State overwritten"
        )

        assert result.success is True
        assert result.policy_applied == ConflictPolicy.CLOBBER
        assert result.error is None

    def test_action_result_failure(self):
        """Test failed ActionResult."""
        result = ActionResult(
            success=False,
            policy_applied=ConflictPolicy.MERGE,
            message="Merge failed",
            error="Conflict on key 'foo'"
        )

        assert result.success is False
        assert result.error == "Conflict on key 'foo'"

    def test_action_result_with_branch(self):
        """Test ActionResult with branch ID."""
        result = ActionResult(
            success=True,
            policy_applied=ConflictPolicy.BRANCH,
            message="Branch created",
            branch_id="branch-abc123"
        )

        assert result.branch_id == "branch-abc123"

    def test_action_result_to_dict(self):
        """Test ActionResult serialization."""
        result = ActionResult(
            success=True,
            policy_applied=ConflictPolicy.MERGE,
            message="Merged",
            merged_state={"key": "value"}
        )

        data = result.to_dict()

        assert data["success"] is True
        assert data["policy_applied"] == "MERGE"
        assert data["merged_state"] == {"key": "value"}


class TestDriftPolicyHandler:
    """Tests for DriftPolicyHandler class."""

    def test_initialization(self):
        """Test handler initialization."""
        handler = DriftPolicyHandler()

        assert handler._merge_strategy == "local"
        assert handler._conflict_resolution == "manual"
        assert len(handler.get_drift_history()) == 0

    def test_initialization_with_options(self):
        """Test handler with custom options."""
        handler = DriftPolicyHandler(
            merge_strategy="external",
            conflict_resolution="prefer_local"
        )

        assert handler._merge_strategy == "external"
        assert handler._conflict_resolution == "prefer_local"

    def test_detect_drift_no_drift(self):
        """Test drift detection with no drift."""
        handler = DriftPolicyHandler()

        local = {"key": "value"}
        external = {"key": "value"}

        report = handler.detect_drift(local, external)

        assert report is None

    def test_detect_drift_with_drift(self):
        """Test drift detection with actual drift."""
        handler = DriftPolicyHandler()

        local = {"key": "value1"}
        external = {"key": "value2"}

        report = handler.detect_drift(local, external)

        assert report is not None
        assert report.local_hash != report.external_hash
        assert "key" in report.affected_keys

    def test_detect_drift_computes_diff(self):
        """Test that detect_drift computes diff summary."""
        handler = DriftPolicyHandler()

        local = {"key1": "local_val", "key2": "same"}
        external = {"key1": "external_val", "key2": "same"}

        report = handler.detect_drift(local, external)

        assert report is not None
        assert "key1" in report.diff_summary
        assert report.diff_summary["key1"]["status"] == "conflict"
        assert "key2" not in report.diff_summary  # No conflict

    def test_detect_drift_local_only_key(self):
        """Test drift detection with local-only key."""
        handler = DriftPolicyHandler()

        local = {"key1": "val", "key2": "only_local"}
        external = {"key1": "val"}

        report = handler.detect_drift(local, external)

        assert "key2" in report.diff_summary
        assert report.diff_summary["key2"]["status"] == "local_only"

    def test_detect_drift_external_only_key(self):
        """Test drift detection with external-only key."""
        handler = DriftPolicyHandler()

        local = {"key1": "val"}
        external = {"key1": "val", "key2": "only_external"}

        report = handler.detect_drift(local, external)

        assert "key2" in report.diff_summary
        assert report.diff_summary["key2"]["status"] == "external_only"

    def test_apply_fail_policy(self):
        """Test FAIL policy raises error."""
        handler = DriftPolicyHandler()

        report = DriftReport(
            local_hash="abc",
            external_hash="xyz"
        )

        with pytest.raises(DriftDetectedError) as exc_info:
            handler.apply_policy(ConflictPolicy.FAIL, report, {}, {})

        assert exc_info.value.report == report

    def test_apply_clobber_policy(self):
        """Test CLOBBER policy overwrites external."""
        handler = DriftPolicyHandler()

        local = {"key": "local_value", "extra": "data"}
        external = {"key": "external_value"}

        report = DriftReport(local_hash="abc", external_hash="xyz")
        result = handler.apply_policy(ConflictPolicy.CLOBBER, report, local, external)

        assert result.success is True
        assert result.merged_state == local
        assert report.resolution == "CLOBBERED"

    def test_apply_merge_policy_simple(self):
        """Test MERGE policy with simple merge."""
        handler = DriftPolicyHandler(merge_strategy="local")

        local = {"key1": "local_val", "key2": "same"}
        external = {"key1": "external_val", "key3": "new"}

        report = DriftReport(local_hash="abc", external_hash="xyz")
        result = handler.apply_policy(ConflictPolicy.MERGE, report, local, external)

        assert result.success is True
        assert result.merged_state is not None
        assert result.merged_state["key2"] == "same"
        assert result.merged_state["key3"] == "new"
        assert report.resolution == "MERGED"

    def test_apply_merge_policy_dict_merge(self):
        """Test MERGE policy with nested dict merge."""
        handler = DriftPolicyHandler()

        local = {"config": {"a": 1, "b": 2}}
        external = {"config": {"a": 1, "c": 3}}

        report = DriftReport(local_hash="abc", external_hash="xyz")
        result = handler.apply_policy(ConflictPolicy.MERGE, report, local, external)

        assert result.success is True
        # Should merge both dicts
        assert "b" in result.merged_state["config"]
        assert "c" in result.merged_state["config"]

    def test_apply_merge_policy_conflict(self):
        """Test MERGE policy with simple conflict uses merge_strategy."""
        handler = DriftPolicyHandler(
            merge_strategy="local",
            conflict_resolution="manual"
        )

        local = {"key": "local"}
        external = {"key": "external"}

        report = DriftReport(local_hash="abc", external_hash="xyz")
        result = handler.apply_policy(ConflictPolicy.MERGE, report, local, external)

        # With merge_strategy="local", should succeed and use local value
        assert result.success is True
        assert result.merged_state["key"] == "local"

    def test_apply_merge_conflict_resolution_triggered(self):
        """Test MERGE policy triggers conflict_resolution when no merge strategy applies."""
        # Create handler with no default merge strategy behavior
        handler = DriftPolicyHandler(conflict_resolution="manual")
        # Override merge strategy to force conflict resolution
        handler._merge_strategy = None

        local = {"key": "local"}
        external = {"key": "external"}

        report = DriftReport(local_hash="abc", external_hash="xyz")
        result = handler.apply_policy(ConflictPolicy.MERGE, report, local, external)

        # Should fail with manual conflict resolution
        assert result.success is False
        assert "MergeConflict" in result.error or "Cannot merge" in result.error

    def test_apply_merge_policy_prefer_local(self):
        """Test MERGE policy with prefer_local conflict resolution."""
        handler = DriftPolicyHandler(conflict_resolution="prefer_local")

        local = {"key": "local"}
        external = {"key": "external"}

        report = DriftReport(local_hash="abc", external_hash="xyz")
        result = handler.apply_policy(ConflictPolicy.MERGE, report, local, external)

        assert result.success is True
        assert result.merged_state["key"] == "local"

    def test_apply_branch_policy(self):
        """Test BRANCH policy creates branch."""
        handler = DriftPolicyHandler()

        local = {"key": "local"}
        external = {"key": "external"}

        report = DriftReport(local_hash="abc", external_hash="xyz")
        result = handler.apply_policy(ConflictPolicy.BRANCH, report, local, external)

        assert result.success is True
        assert result.branch_id is not None
        assert result.branch_id.startswith("branch-")

        # Verify branch was stored
        branch = handler.get_branch(result.branch_id)
        assert branch is not None
        assert branch["local_state"] == local
        assert branch["external_state"] == external

    def test_create_branch(self):
        """Test branch creation."""
        handler = DriftPolicyHandler()

        report = DriftReport(local_hash="abc", external_hash="xyz")
        branch_id = handler.create_branch(report, {"a": 1}, {"b": 2})

        assert branch_id.startswith("branch-")

        branch = handler.get_branch(branch_id)
        assert branch["drift_id"] == report.drift_id
        assert branch["resolved"] is False

    def test_resolve_branch(self):
        """Test branch resolution."""
        handler = DriftPolicyHandler()

        report = DriftReport(local_hash="abc", external_hash="xyz")
        branch_id = handler.create_branch(report, {"a": 1}, {"b": 2})

        # Resolve with local
        success = handler.resolve_branch(branch_id, "local")

        assert success is True
        branch = handler.get_branch(branch_id)
        assert branch["resolved"] is True
        assert branch["resolution"] == "local"
        assert branch["final_state"] == {"a": 1}

    def test_resolve_branch_merged(self):
        """Test branch resolution with merged state."""
        handler = DriftPolicyHandler()

        report = DriftReport(local_hash="abc", external_hash="xyz")
        branch_id = handler.create_branch(report, {"a": 1}, {"b": 2})

        merged = {"a": 1, "b": 2}
        success = handler.resolve_branch(branch_id, "merged", merged)

        assert success is True
        branch = handler.get_branch(branch_id)
        assert branch["final_state"] == merged

    def test_get_stats(self):
        """Test handler statistics."""
        handler = DriftPolicyHandler()

        # Create some drifts
        handler.detect_drift({"a": 1}, {"a": 2})
        handler.detect_drift({"b": 1}, {"b": 2})

        stats = handler.get_stats()

        assert stats["total_drifts_detected"] == 2
        assert stats["branches_created"] == 0

    def test_get_drift_history(self):
        """Test drift history retrieval."""
        handler = DriftPolicyHandler()

        # Create drifts
        handler.detect_drift({"a": 1}, {"a": 2})
        handler.detect_drift({"b": 1}, {"b": 2})

        history = handler.get_drift_history()

        assert len(history) == 2


class TestMergeStrategy:
    """Tests for merge strategy handling."""

    def test_merge_lists_simple(self):
        """Test list merge with simple values."""
        handler = DriftPolicyHandler()

        local = [1, 2, 3]
        external = [3, 4, 5]

        merged = handler._merge_lists(local, external)

        # Should deduplicate and preserve order
        assert 3 in merged
        assert 4 in merged
        assert 5 in merged
        assert len([x for x in merged if x == 3]) == 1  # No duplicates

    def test_merge_strategy_local(self):
        """Test merge strategy preferring local."""
        handler = DriftPolicyHandler(merge_strategy="local")

        result = handler._merge_field("key", "local_val", "external_val")

        assert result == "local_val"

    def test_merge_strategy_external(self):
        """Test merge strategy preferring external."""
        handler = DriftPolicyHandler(merge_strategy="external")

        result = handler._merge_field("key", "local_val", "external_val")

        assert result == "external_val"

    def test_merge_strategy_newer(self):
        """Test merge strategy preferring newer timestamp."""
        handler = DriftPolicyHandler(merge_strategy="newer")

        older = "2024-01-01T00:00:00Z"
        newer = "2024-01-02T00:00:00Z"

        result = handler._merge_field("updated_at", newer, older)

        assert result == newer


class TestEventBusIntegration:
    """Tests for EventBus integration."""

    def test_state_drift_event_emitted(self):
        """Test that STATE_DRIFT event is emitted."""
        event_bus = EventBus()
        handler = DriftPolicyHandler(event_bus=event_bus)

        events_received = []

        def capture_event(event):
            events_received.append(event)

        event_bus.subscribe("STATE_DRIFT", capture_event)

        local = {"key": "value1"}
        external = {"key": "value2"}

        handler.detect_drift(local, external)

        assert len(events_received) == 1
        assert events_received[0].event_type == "STATE_DRIFT"

    def test_drift_resolved_event_on_merge(self):
        """Test that DRIFT_RESOLVED event is emitted on merge."""
        event_bus = EventBus()
        handler = DriftPolicyHandler(
            event_bus=event_bus,
            conflict_resolution="prefer_local"
        )

        events_received = []

        def capture_event(event):
            events_received.append(event)

        event_bus.subscribe("DRIFT_RESOLVED", capture_event)

        local = {"key": "local"}
        external = {"key": "external"}

        report = DriftReport(local_hash="abc", external_hash="xyz")
        handler.apply_policy(ConflictPolicy.MERGE, report, local, external)

        assert len(events_received) == 1
        assert events_received[0].event_type == "DRIFT_RESOLVED"

    def test_branch_created_event(self):
        """Test that BRANCH_CREATED event is emitted."""
        event_bus = EventBus()
        handler = DriftPolicyHandler(event_bus=event_bus)

        events_received = []

        def capture_event(event):
            events_received.append(event)

        event_bus.subscribe("BRANCH_CREATED", capture_event)

        local = {"key": "local"}
        external = {"key": "external"}

        report = DriftReport(local_hash="abc", external_hash="xyz")
        handler.apply_policy(ConflictPolicy.BRANCH, report, local, external)

        assert len(events_received) == 1
        assert events_received[0].event_type == "BRANCH_CREATED"


class TestCursorTrackerIntegration:
    """Tests for CursorTracker integration with DriftPolicyHandler."""

    def test_validate_and_handle_drift_no_drift(self):
        """Test validate_and_handle_drift with no drift."""
        tracker = CursorTracker()

        state = {"key": "value"}
        result = tracker.validate_and_handle_drift(
            policy=ConflictPolicy.FAIL,
            local_state=state,
            external_state=state
        )

        assert result.success is True
        assert "No drift detected" in result.message

    def test_validate_and_handle_drift_with_clobber(self):
        """Test validate_and_handle_drift with CLOBBER policy."""
        tracker = CursorTracker()

        local = {"key": "local_val"}
        external = {"key": "external_val"}

        result = tracker.validate_and_handle_drift(
            policy=ConflictPolicy.CLOBBER,
            local_state=local,
            external_state=external
        )

        assert result.success is True
        assert result.merged_state == local

    def test_validate_and_handle_drift_with_fail_raises(self):
        """Test validate_and_handle_drift with FAIL policy raises."""
        tracker = CursorTracker()

        local = {"key": "local"}
        external = {"key": "external"}

        with pytest.raises(DriftDetectedError):
            tracker.validate_and_handle_drift(
                policy=ConflictPolicy.FAIL,
                local_state=local,
                external_state=external
            )

    def test_get_drift_handler(self):
        """Test getting drift handler from tracker."""
        tracker = CursorTracker()

        handler = tracker.get_drift_handler()

        assert isinstance(handler, DriftPolicyHandler)

    def test_drift_handler_with_event_bus(self):
        """Test that drift handler uses tracker's EventBus."""
        event_bus = EventBus()
        tracker = CursorTracker(event_bus=event_bus)

        events_received = []

        def capture_event(event):
            events_received.append(event)

        event_bus.subscribe("STATE_DRIFT", capture_event)

        local = {"key": "local"}
        external = {"key": "external"}

        tracker.validate_and_handle_drift(
            policy=ConflictPolicy.CLOBBER,
            local_state=local,
            external_state=external
        )

        assert len(events_received) == 1


class TestConvenienceFunction:
    """Tests for convenience function."""

    def test_check_state_drift_no_drift(self):
        """Test check_state_drift with no drift."""
        state = {"key": "value"}

        result = check_state_drift(state, state)

        assert result is None

    def test_check_state_drift_with_drift(self):
        """Test check_state_drift with drift."""
        local = {"key": "value1"}
        external = {"key": "value2"}

        result = check_state_drift(local, external)

        assert result is not None
        assert result.local_hash != result.external_hash


class TestEventTypes:
    """Tests for EventTypes constants."""

    def test_drift_event_types_exist(self):
        """Test that drift event types are defined."""
        assert hasattr(EventTypes, 'STATE_DRIFT')
        assert hasattr(EventTypes, 'DRIFT_RESOLVED')
        assert hasattr(EventTypes, 'BRANCH_CREATED')

    def test_drift_event_type_values(self):
        """Test drift event type values."""
        assert EventTypes.STATE_DRIFT == "STATE_DRIFT"
        assert EventTypes.DRIFT_RESOLVED == "DRIFT_RESOLVED"
        assert EventTypes.BRANCH_CREATED == "BRANCH_CREATED"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
