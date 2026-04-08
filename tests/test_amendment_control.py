"""
Tests for ITEM-DAG-114: Root Model Plan Amendment Control

This module tests the amendment control system that ensures all DAG
modifications require proper validation and approval.

Author: TITAN FUSE Team
Version: 4.0.0
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from src.planning.amendment_control import (
    Amendment,
    AmendmentRequest,
    AmendmentStatus,
    AmendmentType,
    AmendmentController,
    create_amendment_controller,
)
from src.events.event_bus import EventBus, Event, EventSeverity, EventTypes


class TestAmendmentStatus:
    """Tests for AmendmentStatus enum."""

    def test_status_values(self):
        """Test that status values are correct."""
        assert AmendmentStatus.PENDING.value == "pending"
        assert AmendmentStatus.APPROVED.value == "approved"
        assert AmendmentStatus.REJECTED.value == "rejected"

    def test_all_statuses_exist(self):
        """Test that all required statuses exist."""
        statuses = [s.value for s in AmendmentStatus]
        assert "pending" in statuses
        assert "approved" in statuses
        assert "rejected" in statuses


class TestAmendmentType:
    """Tests for AmendmentType enum."""

    def test_amendment_types_exist(self):
        """Test that all amendment types are defined."""
        assert hasattr(AmendmentType, "ADD_STEP")
        assert hasattr(AmendmentType, "REMOVE_STEP")
        assert hasattr(AmendmentType, "MODIFY_DEPENDENCY")
        assert hasattr(AmendmentType, "CHANGE_PRIORITY")
        assert hasattr(AmendmentType, "ADD_BATCH")
        assert hasattr(AmendmentType, "REMOVE_BATCH")
        assert hasattr(AmendmentType, "MODIFY_EXECUTION_ORDER")
        assert hasattr(AmendmentType, "CHANGE_KEEP_VETO")


class TestAmendment:
    """Tests for Amendment dataclass."""

    def test_amendment_creation(self):
        """Test creating an amendment."""
        amendment = Amendment(
            amendment_type=AmendmentType.ADD_STEP,
            target="step-123",
            changes={"name": "new_step", "dependencies": []},
            reason="Need additional processing step",
            requester="root_model"
        )
        
        assert amendment.amendment_type == AmendmentType.ADD_STEP
        assert amendment.target == "step-123"
        assert amendment.changes == {"name": "new_step", "dependencies": []}
        assert amendment.reason == "Need additional processing step"
        assert amendment.requester == "root_model"

    def test_amendment_to_dict(self):
        """Test amendment serialization."""
        amendment = Amendment(
            amendment_type=AmendmentType.REMOVE_STEP,
            target="step-456",
            changes={"cascade": True},
            reason="Step no longer needed",
            requester="planner",
            metadata={"priority": "high"}
        )
        
        d = amendment.to_dict()
        
        assert d["amendment_type"] == "remove_step"
        assert d["target"] == "step-456"
        assert d["changes"] == {"cascade": True}
        assert d["reason"] == "Step no longer needed"
        assert d["requester"] == "planner"
        assert d["metadata"] == {"priority": "high"}

    def test_amendment_from_dict(self):
        """Test amendment deserialization."""
        d = {
            "amendment_type": "modify_dependency",
            "target": "step-789",
            "changes": {"depends_on": ["step-1", "step-2"]},
            "reason": "Fix dependency chain",
            "requester": "validator",
            "metadata": {}
        }
        
        amendment = Amendment.from_dict(d)
        
        assert amendment.amendment_type == AmendmentType.MODIFY_DEPENDENCY
        assert amendment.target == "step-789"
        assert amendment.changes == {"depends_on": ["step-1", "step-2"]}
        assert amendment.reason == "Fix dependency chain"
        assert amendment.requester == "validator"


class TestAmendmentRequest:
    """Tests for AmendmentRequest dataclass."""

    def test_request_creation(self):
        """Test creating an amendment request."""
        amendment = Amendment(
            amendment_type=AmendmentType.ADD_STEP,
            target="step-123",
            changes={"name": "new_step"},
            reason="Test reason",
            requester="test"
        )
        
        request = AmendmentRequest(
            request_id="AMEND-20240101-0001",
            amendment=amendment,
            created_by="test_user"
        )
        
        assert request.request_id == "AMEND-20240101-0001"
        assert request.amendment == amendment
        assert request.status == AmendmentStatus.PENDING
        assert request.created_by == "test_user"
        assert len(request.audit_entries) == 1  # Initial audit entry

    def test_request_to_dict(self):
        """Test request serialization."""
        amendment = Amendment(
            amendment_type=AmendmentType.CHANGE_PRIORITY,
            target="step-123",
            changes={"priority": 1},
            reason="Increase priority",
            requester="test"
        )
        
        request = AmendmentRequest(
            request_id="AMEND-001",
            amendment=amendment,
            status=AmendmentStatus.APPROVED,
            created_by="user1",
            approved_by="admin1"
        )
        
        d = request.to_dict()
        
        assert d["request_id"] == "AMEND-001"
        assert d["status"] == "approved"
        assert d["created_by"] == "user1"
        assert d["approved_by"] == "admin1"
        assert "amendment" in d

    def test_request_from_dict(self):
        """Test request deserialization."""
        d = {
            "request_id": "AMEND-002",
            "amendment": {
                "amendment_type": "add_step",
                "target": "step-new",
                "changes": {"name": "new"},
                "reason": "Test",
                "requester": "tester",
                "metadata": {}
            },
            "status": "rejected",
            "created_at": "2024-01-01T00:00:00Z",
            "created_by": "user2",
            "rejection_reason": "Invalid target"
        }
        
        request = AmendmentRequest.from_dict(d)
        
        assert request.request_id == "AMEND-002"
        assert request.status == AmendmentStatus.REJECTED
        assert request.rejection_reason == "Invalid target"

    def test_add_audit_entry(self):
        """Test adding audit entries."""
        amendment = Amendment(
            amendment_type=AmendmentType.ADD_STEP,
            target="step-123",
            changes={},
            reason="Test",
            requester="test"
        )
        
        request = AmendmentRequest(
            request_id="AMEND-003",
            amendment=amendment
        )
        
        initial_count = len(request.audit_entries)
        request.add_audit_entry("validated", "Gate validation passed")
        
        assert len(request.audit_entries) == initial_count + 1
        assert request.audit_entries[-1]["action"] == "validated"
        assert request.audit_entries[-1]["details"] == "Gate validation passed"


class TestAmendmentController:
    """Tests for AmendmentController class."""

    @pytest.fixture
    def controller(self):
        """Create a basic controller for testing."""
        return AmendmentController()

    @pytest.fixture
    def controller_with_bus(self):
        """Create a controller with EventBus."""
        bus = EventBus(config={"async_enabled": False})
        controller = AmendmentController(event_bus=bus)
        return controller, bus

    @pytest.fixture
    def sample_amendment(self):
        """Create a sample amendment for testing."""
        return Amendment(
            amendment_type=AmendmentType.ADD_STEP,
            target="step-123",
            changes={"name": "new_step", "dependencies": []},
            reason="Need additional processing step",
            requester="root_model"
        )

    def test_controller_initialization(self, controller):
        """Test controller initialization."""
        assert controller is not None
        stats = controller.get_stats()
        assert stats["total_requests"] == 0
        assert stats["pending"] == 0
        assert stats["approved"] == 0
        assert stats["rejected"] == 0

    def test_request_amendment(self, controller, sample_amendment):
        """Test requesting an amendment."""
        request = controller.request_amendment(sample_amendment)
        
        assert request is not None
        assert request.request_id.startswith("AMEND-")
        assert request.status == AmendmentStatus.PENDING
        assert request.amendment == sample_amendment
        
        # Verify stats updated
        stats = controller.get_stats()
        assert stats["total_requests"] == 1
        assert stats["pending"] == 1

    def test_request_amendment_validates_target(self, controller):
        """Test that amendment requires a target."""
        amendment = Amendment(
            amendment_type=AmendmentType.ADD_STEP,
            target="",  # Empty target
            changes={},
            reason="Test",
            requester="test"
        )
        
        with pytest.raises(ValueError, match="must have a target"):
            controller.request_amendment(amendment)

    def test_request_amendment_validates_reason(self, controller):
        """Test that amendment requires a reason."""
        amendment = Amendment(
            amendment_type=AmendmentType.ADD_STEP,
            target="step-123",
            changes={},
            reason="",  # Empty reason
            requester="test"
        )
        
        with pytest.raises(ValueError, match="must have a reason"):
            controller.request_amendment(amendment)

    def test_request_amendment_validates_requester(self, controller):
        """Test that amendment requires a requester."""
        amendment = Amendment(
            amendment_type=AmendmentType.ADD_STEP,
            target="step-123",
            changes={},
            reason="Test",
            requester=""  # Empty requester
        )
        
        with pytest.raises(ValueError, match="must have a requester"):
            controller.request_amendment(amendment)

    def test_approve_amendment(self, controller, sample_amendment):
        """Test approving an amendment."""
        request = controller.request_amendment(sample_amendment)
        
        # Without GateManager, validation should pass
        result = controller.approve_amendment(request.request_id, "admin")
        
        assert result is True
        
        # Verify status changed
        updated = controller.get_request(request.request_id)
        assert updated.status == AmendmentStatus.APPROVED
        assert updated.approved_by == "admin"
        assert updated.approved_at is not None

    def test_approve_nonexistent_request(self, controller):
        """Test approving a non-existent request."""
        with pytest.raises(ValueError, match="not found"):
            controller.approve_amendment("INVALID-ID")

    def test_approve_already_processed_request(self, controller, sample_amendment):
        """Test approving an already processed request."""
        request = controller.request_amendment(sample_amendment)
        controller.approve_amendment(request.request_id, "admin")
        
        with pytest.raises(ValueError, match="status is approved"):
            controller.approve_amendment(request.request_id, "admin2")

    def test_reject_amendment(self, controller, sample_amendment):
        """Test rejecting an amendment."""
        request = controller.request_amendment(sample_amendment)
        
        controller.reject_amendment(request.request_id, "Invalid target", "admin")
        
        # Verify status changed
        updated = controller.get_request(request.request_id)
        assert updated.status == AmendmentStatus.REJECTED
        assert updated.rejection_reason == "Invalid target"

    def test_reject_nonexistent_request(self, controller):
        """Test rejecting a non-existent request."""
        with pytest.raises(ValueError, match="not found"):
            controller.reject_amendment("INVALID-ID", "Not found")

    def test_get_pending_requests(self, controller):
        """Test getting pending requests."""
        # Create multiple requests
        for i in range(3):
            amendment = Amendment(
                amendment_type=AmendmentType.ADD_STEP,
                target=f"step-{i}",
                changes={},
                reason=f"Reason {i}",
                requester="test"
            )
            controller.request_amendment(amendment)
        
        # Approve one
        pending = controller.get_pending_requests()
        controller.approve_amendment(pending[0].request_id, "admin")
        
        # Check counts
        assert len(controller.get_pending_requests()) == 2
        assert len(controller.get_approved_requests()) == 1

    def test_get_approved_requests(self, controller):
        """Test getting approved requests."""
        amendment = Amendment(
            amendment_type=AmendmentType.ADD_STEP,
            target="step-1",
            changes={},
            reason="Test",
            requester="test"
        )
        request = controller.request_amendment(amendment)
        controller.approve_amendment(request.request_id, "admin")
        
        approved = controller.get_approved_requests()
        assert len(approved) == 1
        assert approved[0].request_id == request.request_id

    def test_get_rejected_requests(self, controller):
        """Test getting rejected requests."""
        amendment = Amendment(
            amendment_type=AmendmentType.ADD_STEP,
            target="step-1",
            changes={},
            reason="Test",
            requester="test"
        )
        request = controller.request_amendment(amendment)
        controller.reject_amendment(request.request_id, "Rejected", "admin")
        
        rejected = controller.get_rejected_requests()
        assert len(rejected) == 1
        assert rejected[0].request_id == request.request_id

    def test_history_tracking(self, controller, sample_amendment):
        """Test that history is tracked."""
        request = controller.request_amendment(sample_amendment)
        controller.approve_amendment(request.request_id, "admin")
        
        history = controller.get_history()
        assert len(history) == 2  # Request + Approve
        assert history[0]["action"] == "requested"
        assert history[1]["action"] == "approved"

    def test_event_emission_on_request(self, controller_with_bus, sample_amendment):
        """Test that events are emitted on request."""
        controller, bus = controller_with_bus
        
        events_received = []
        
        def handler(event):
            events_received.append(event)
        
        bus.subscribe("PLAN_AMENDMENT_REQUESTED", handler)
        
        controller.request_amendment(sample_amendment)
        
        assert len(events_received) == 1
        assert events_received[0].event_type == "PLAN_AMENDMENT_REQUESTED"
        assert events_received[0].data["amendment_type"] == "add_step"

    def test_event_emission_on_approve(self, controller_with_bus, sample_amendment):
        """Test that events are emitted on approve."""
        controller, bus = controller_with_bus
        
        events_received = []
        
        def handler(event):
            events_received.append(event)
        
        bus.subscribe("PLAN_AMENDMENT_APPROVED", handler)
        
        request = controller.request_amendment(sample_amendment)
        controller.approve_amendment(request.request_id, "admin")
        
        assert len(events_received) == 1
        assert events_received[0].event_type == "PLAN_AMENDMENT_APPROVED"

    def test_event_emission_on_reject(self, controller_with_bus, sample_amendment):
        """Test that events are emitted on reject."""
        controller, bus = controller_with_bus
        
        events_received = []
        
        def handler(event):
            events_received.append(event)
        
        bus.subscribe("PLAN_AMENDMENT_REJECTED", handler)
        
        request = controller.request_amendment(sample_amendment)
        controller.reject_amendment(request.request_id, "Test rejection", "admin")
        
        assert len(events_received) == 1
        assert events_received[0].event_type == "PLAN_AMENDMENT_REJECTED"
        assert events_received[0].data["reason"] == "Test rejection"

    def test_custom_validation_hook(self, controller, sample_amendment):
        """Test custom validation hooks."""
        # Add a hook that rejects certain targets
        def reject_protected(amendment):
            return not amendment.target.startswith("protected-")
        
        controller.add_validation_hook(reject_protected)
        
        # This should pass
        request = controller.request_amendment(sample_amendment)
        result = controller.approve_amendment(request.request_id, "admin")
        assert result is True
        
        # This should fail validation
        protected_amendment = Amendment(
            amendment_type=AmendmentType.ADD_STEP,
            target="protected-step",
            changes={},
            reason="Test",
            requester="test"
        )
        protected_request = controller.request_amendment(protected_amendment)
        result = controller.approve_amendment(protected_request.request_id, "admin")
        assert result is False

    def test_validation_hook_exception_handling(self, controller, sample_amendment):
        """Test that hook exceptions are handled."""
        def failing_hook(amendment):
            raise RuntimeError("Hook error")
        
        controller.add_validation_hook(failing_hook)
        
        request = controller.request_amendment(sample_amendment)
        result = controller.approve_amendment(request.request_id, "admin")
        
        # Should fail due to hook exception
        assert result is False
        
        updated = controller.get_request(request.request_id)
        assert updated.status == AmendmentStatus.REJECTED
        assert "error" in updated.rejection_reason.lower()

    def test_gate_manager_integration(self, sample_amendment):
        """Test integration with GateManager."""
        from src.policy.gate_manager import GateManager, GateResult
        
        gate_manager = GateManager()
        controller = AmendmentController(gate_manager=gate_manager)
        
        request = controller.request_amendment(sample_amendment)
        result = controller.approve_amendment(request.request_id, "admin")
        
        # Without proper context, gates may fail but should not crash
        assert isinstance(result, bool)

    def test_factory_function(self):
        """Test the factory function."""
        controller = create_amendment_controller()
        assert controller is not None
        
        bus = EventBus()
        controller_with_bus = create_amendment_controller(event_bus=bus)
        assert controller_with_bus._event_bus == bus

    def test_set_event_bus(self, controller):
        """Test setting EventBus after creation."""
        bus = EventBus()
        controller.set_event_bus(bus)
        assert controller._event_bus == bus

    def test_set_gate_manager(self, controller):
        """Test setting GateManager after creation."""
        from src.policy.gate_manager import GateManager
        gm = GateManager()
        controller.set_gate_manager(gm)
        assert controller._gate_manager == gm


class TestAmendmentControllerProtectedFields:
    """Tests for protected field handling."""

    def test_protected_fields_logged(self):
        """Test that modifications to protected fields are logged."""
        controller = AmendmentController()
        
        with patch.object(controller._logger, 'warning') as mock_warning:
            amendment = Amendment(
                amendment_type=AmendmentType.MODIFY_EXECUTION_ORDER,
                target="plan",
                changes={"execution_order": ["step-3", "step-1", "step-2"]},
                reason="Reorder execution",
                requester="optimizer"
            )
            controller.request_amendment(amendment)
            
            # Should log warning about protected field
            mock_warning.assert_called()
            assert "execution_order" in str(mock_warning.call_args)


class TestEventSeverityMapping:
    """Tests for event severity mapping of amendment events."""

    def test_amendment_requested_is_info(self):
        """Test that PLAN_AMENDMENT_REQUESTED is INFO severity."""
        from src.events.event_bus import get_severity_for_event
        assert get_severity_for_event("PLAN_AMENDMENT_REQUESTED") == EventSeverity.INFO

    def test_amendment_approved_is_info(self):
        """Test that PLAN_AMENDMENT_APPROVED is INFO severity."""
        from src.events.event_bus import get_severity_for_event
        assert get_severity_for_event("PLAN_AMENDMENT_APPROVED") == EventSeverity.INFO

    def test_amendment_rejected_is_warn(self):
        """Test that PLAN_AMENDMENT_REJECTED is WARN severity."""
        from src.events.event_bus import get_severity_for_event
        assert get_severity_for_event("PLAN_AMENDMENT_REJECTED") == EventSeverity.WARN


class TestEventTypesConstants:
    """Tests for EventTypes constants."""

    def test_amendment_event_types_exist(self):
        """Test that amendment event types are defined in EventTypes."""
        assert hasattr(EventTypes, "PLAN_AMENDMENT_REQUESTED")
        assert hasattr(EventTypes, "PLAN_AMENDMENT_APPROVED")
        assert hasattr(EventTypes, "PLAN_AMENDMENT_REJECTED")

    def test_amendment_event_types_values(self):
        """Test that amendment event types have correct values."""
        assert EventTypes.PLAN_AMENDMENT_REQUESTED == "PLAN_AMENDMENT_REQUESTED"
        assert EventTypes.PLAN_AMENDMENT_APPROVED == "PLAN_AMENDMENT_APPROVED"
        assert EventTypes.PLAN_AMENDMENT_REJECTED == "PLAN_AMENDMENT_REJECTED"


class TestAmendmentRequestUniqueIds:
    """Tests for unique request ID generation."""

    def test_unique_ids_generated(self):
        """Test that each request gets a unique ID."""
        controller = AmendmentController()
        
        amendment1 = Amendment(
            amendment_type=AmendmentType.ADD_STEP,
            target="step-1",
            changes={},
            reason="Test 1",
            requester="test"
        )
        
        amendment2 = Amendment(
            amendment_type=AmendmentType.ADD_STEP,
            target="step-2",
            changes={},
            reason="Test 2",
            requester="test"
        )
        
        request1 = controller.request_amendment(amendment1)
        request2 = controller.request_amendment(amendment2)
        
        assert request1.request_id != request2.request_id


class TestAmendmentAuditTrail:
    """Tests for audit trail functionality."""

    def test_audit_trail_complete(self):
        """Test that audit trail captures all actions."""
        controller = AmendmentController()
        
        amendment = Amendment(
            amendment_type=AmendmentType.ADD_STEP,
            target="step-1",
            changes={},
            reason="Test",
            requester="test"
        )
        
        request = controller.request_amendment(amendment)
        controller.approve_amendment(request.request_id, "admin")
        
        updated = controller.get_request(request.request_id)
        
        # Should have at least: created, approved
        assert len(updated.audit_entries) >= 2
        
        actions = [e["action"] for e in updated.audit_entries]
        assert "created" in actions
        assert "approved" in actions

    def test_audit_trail_with_rejection(self):
        """Test audit trail with rejection."""
        controller = AmendmentController()
        
        amendment = Amendment(
            amendment_type=AmendmentType.ADD_STEP,
            target="step-1",
            changes={},
            reason="Test",
            requester="test"
        )
        
        request = controller.request_amendment(amendment)
        controller.reject_amendment(request.request_id, "Test rejection", "admin")
        
        updated = controller.get_request(request.request_id)
        
        actions = [e["action"] for e in updated.audit_entries]
        assert "rejected" in actions
        
        rejection_entry = next(e for e in updated.audit_entries if e["action"] == "rejected")
        assert "Test rejection" in rejection_entry["details"]


class TestAmendmentValidationCriteria:
    """Tests for validation criteria from requirements."""

    def test_amendment_required_for_dag_changes(self):
        """
        Validation criterion: amendment_required
        
        Test that amendment is required for DAG changes.
        Direct modification should not be possible without request.
        """
        controller = AmendmentController()
        
        # There's no direct "apply_amendment" method that bypasses approval
        # All modifications must go through request_amendment
        amendment = Amendment(
            amendment_type=AmendmentType.MODIFY_DEPENDENCY,
            target="step-1",
            changes={"dependencies": ["step-2"]},
            reason="Fix dependency",
            requester="test"
        )
        
        # Must create a request first
        request = controller.request_amendment(amendment)
        assert request.status == AmendmentStatus.PENDING
        
        # Request must be approved before changes can be applied
        # (Application is external - controller only handles approval)
        approved = controller.approve_amendment(request.request_id, "admin")
        assert approved is True

    def test_all_amendments_logged(self):
        """
        Validation criterion: audit_logged
        
        Test that all amendments are logged.
        """
        controller = AmendmentController()
        
        # Create, approve, and reject some amendments
        for i in range(3):
            amendment = Amendment(
                amendment_type=AmendmentType.ADD_STEP,
                target=f"step-{i}",
                changes={},
                reason=f"Reason {i}",
                requester="test"
            )
            request = controller.request_amendment(amendment)
            
            if i == 0:
                controller.approve_amendment(request.request_id, "admin")
            elif i == 1:
                controller.reject_amendment(request.request_id, "Test", "admin")
            # i == 2 stays pending
        
        # Check history contains all actions
        history = controller.get_history()
        assert len(history) == 5  # 3 requests + 1 approve + 1 reject
        
        actions = [h["action"] for h in history]
        assert actions.count("requested") == 3
        assert actions.count("approved") == 1
        assert actions.count("rejected") == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
