"""
Tests for ITEM-OPS-139: Human-in-the-Loop Escalation Protocol.

This test module verifies the escalation protocol with SLA tracking.
"""

import pytest
from datetime import datetime, timezone, timedelta
import sys
import os
import threading
import time

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.approval.escalation import (
    EscalationProtocol,
    EscalationRecord,
    EscalationOption,
    EscalationStatus,
    SLAStatus,
    Severity,
    SLA_DURATIONS,
    create_escalation_protocol,
)
from src.utils.timezone import now_utc, now_utc_iso, to_iso8601


class TestEscalationOption:
    """Tests for EscalationOption dataclass."""

    def test_create_option_basic(self):
        """Test creating a basic escalation option."""
        option = EscalationOption(
            id="approve",
            label="Approve",
            description="Approve the request",
        )
        assert option.id == "approve"
        assert option.label == "Approve"
        assert option.description == "Approve the request"
        assert option.risk_level == "medium"
        assert option.recommended is False
        assert option.consequences == ""

    def test_create_option_full(self):
        """Test creating an escalation option with all fields."""
        option = EscalationOption(
            id="reject",
            label="Reject",
            description="Reject the request",
            risk_level="high",
            recommended=False,
            consequences="User will be notified of rejection",
        )
        assert option.risk_level == "high"
        assert option.recommended is False
        assert option.consequences == "User will be notified of rejection"

    def test_option_to_dict(self):
        """Test converting option to dictionary."""
        option = EscalationOption(
            id="approve",
            label="Approve",
            description="Approve the request",
            risk_level="low",
            recommended=True,
        )
        result = option.to_dict()
        assert result["id"] == "approve"
        assert result["label"] == "Approve"
        assert result["recommended"] is True


class TestEscalationRecord:
    """Tests for EscalationRecord dataclass."""

    def test_create_record_basic(self):
        """Test creating a basic escalation record."""
        record = EscalationRecord(
            id="ESC-123",
            timestamp=now_utc_iso(),
            context={"request_id": "REQ-001"},
            severity="high",
        )
        assert record.id == "ESC-123"
        assert record.context == {"request_id": "REQ-001"}
        assert record.severity == "high"
        assert record.status == EscalationStatus.PENDING
        assert record.escalation_level == 1
        assert record.options == []

    def test_create_record_with_options(self):
        """Test creating an escalation record with options."""
        options = [
            EscalationOption(id="approve", label="Approve", description="Approve"),
            EscalationOption(id="reject", label="Reject", description="Reject"),
        ]
        record = EscalationRecord(
            id="ESC-124",
            timestamp=now_utc_iso(),
            context={},
            severity="medium",
            options=options,
        )
        assert len(record.options) == 2
        assert record.options[0].id == "approve"

    def test_record_to_dict(self):
        """Test converting record to dictionary."""
        record = EscalationRecord(
            id="ESC-125",
            timestamp="2025-01-01T12:00:00Z",
            context={"key": "value"},
            severity="critical",
            escalation_level=2,
            sla_deadline="2025-01-01T12:15:00Z",
        )
        result = record.to_dict()
        assert result["id"] == "ESC-125"
        assert result["severity"] == "critical"
        assert result["escalation_level"] == 2
        assert result["status"] == "pending"

    def test_record_from_dict(self):
        """Test creating record from dictionary."""
        data = {
            "id": "ESC-126",
            "timestamp": "2025-01-01T12:00:00Z",
            "context": {"test": "data"},
            "severity": "low",
            "status": "resolved",
            "escalation_level": 3,
            "selected_option": "approve",
            "reviewer": "alice",
            "rationale": "Meets all criteria",
            "options": [
                {"id": "approve", "label": "Approve", "description": "Approve request"}
            ],
        }
        record = EscalationRecord.from_dict(data)
        assert record.id == "ESC-126"
        assert record.severity == "low"
        assert record.status == EscalationStatus.RESOLVED
        assert record.selected_option == "approve"
        assert record.reviewer == "alice"
        assert len(record.options) == 1


class TestSLAStatus:
    """Tests for SLAStatus dataclass."""

    def test_sla_status_creation(self):
        """Test creating an SLA status."""
        status = SLAStatus(
            escalation_id="ESC-123",
            level=1,
            deadline="2025-01-01T12:15:00Z",
            time_remaining=900.0,
            is_breached=False,
            is_warning=False,
        )
        assert status.escalation_id == "ESC-123"
        assert status.level == 1
        assert status.time_remaining == 900.0
        assert status.is_breached is False

    def test_sla_status_breached(self):
        """Test SLA status when breached."""
        status = SLAStatus(
            escalation_id="ESC-124",
            level=1,
            deadline="2025-01-01T12:00:00Z",
            time_remaining=-60.0,
            is_breached=True,
            is_warning=False,
        )
        assert status.is_breached is True
        assert status.time_remaining < 0

    def test_sla_status_to_dict(self):
        """Test converting SLA status to dictionary."""
        status = SLAStatus(
            escalation_id="ESC-125",
            level=2,
            deadline="2025-01-01T13:00:00Z",
            time_remaining=3600.0,
            is_breached=False,
            is_warning=True,
        )
        result = status.to_dict()
        assert result["escalation_id"] == "ESC-125"
        assert result["is_warning"] is True


class TestEscalationProtocol:
    """Tests for EscalationProtocol class."""

    def test_create_protocol(self):
        """Test creating an escalation protocol."""
        protocol = EscalationProtocol()
        assert protocol is not None
        stats = protocol.get_stats()
        assert stats["total"] == 0

    def test_create_escalation(self):
        """Test creating an escalation."""
        protocol = EscalationProtocol()

        record = protocol.create_escalation(
            context={"request_id": "REQ-001", "user": "alice"},
            severity="high",
            level=1,
        )

        assert record.id.startswith("ESC-")
        assert record.severity == "high"
        assert record.escalation_level == 1
        assert record.status == EscalationStatus.PENDING
        assert record.context["request_id"] == "REQ-001"
        assert record.sla_deadline != ""

    def test_create_escalation_with_options(self):
        """Test creating an escalation with options."""
        protocol = EscalationProtocol()

        options = [
            EscalationOption(
                id="approve",
                label="Approve",
                description="Approve the request",
                risk_level="low",
                recommended=True,
            ),
            EscalationOption(
                id="reject",
                label="Reject",
                description="Reject the request",
                risk_level="medium",
            ),
        ]

        record = protocol.create_escalation(
            context={"request_id": "REQ-002"},
            severity="medium",
            options=options,
            level=2,
        )

        assert len(record.options) == 2
        assert record.options[0].recommended is True

    def test_create_escalation_invalid_level(self):
        """Test that invalid level raises ValueError."""
        protocol = EscalationProtocol()

        with pytest.raises(ValueError, match="Invalid escalation level"):
            protocol.create_escalation(
                context={},
                severity="high",
                level=4,  # Invalid level
            )

    def test_present_options(self):
        """Test presenting options for an escalation."""
        protocol = EscalationProtocol()

        options = [
            EscalationOption(id="opt1", label="Option 1", description="First option"),
            EscalationOption(id="opt2", label="Option 2", description="Second option"),
        ]

        record = protocol.create_escalation(
            context={},
            severity="low",
            options=options,
        )

        presented = protocol.present_options(record.id)
        assert len(presented) == 2
        assert presented[0].id == "opt1"

    def test_present_options_not_found(self):
        """Test presenting options for non-existent escalation."""
        protocol = EscalationProtocol()

        with pytest.raises(KeyError, match="Escalation not found"):
            protocol.present_options("ESC-NONEXISTENT")

    def test_capture_decision(self):
        """Test capturing a decision."""
        protocol = EscalationProtocol()

        options = [
            EscalationOption(id="approve", label="Approve", description="Approve"),
            EscalationOption(id="reject", label="Reject", description="Reject"),
        ]

        record = protocol.create_escalation(
            context={"request_id": "REQ-003"},
            severity="high",
            options=options,
        )

        result = protocol.capture_decision(
            escalation_id=record.id,
            selected_option="approve",
            reviewer="bob",
            rationale="Request meets all criteria",
        )

        assert result is True

        # Verify the record was updated
        updated = protocol.get_escalation(record.id)
        assert updated.selected_option == "approve"
        assert updated.reviewer == "bob"
        assert updated.rationale == "Request meets all criteria"
        assert updated.status == EscalationStatus.RESOLVED
        assert updated.resolved_at is not None

    def test_capture_decision_invalid_option(self):
        """Test capturing decision with invalid option."""
        protocol = EscalationProtocol()

        options = [
            EscalationOption(id="approve", label="Approve", description="Approve"),
        ]

        record = protocol.create_escalation(
            context={},
            severity="medium",
            options=options,
        )

        with pytest.raises(ValueError, match="Invalid option"):
            protocol.capture_decision(
                escalation_id=record.id,
                selected_option="invalid_option",
                reviewer="bob",
                rationale="Test",
            )

    def test_capture_decision_not_pending(self):
        """Test capturing decision for non-pending escalation."""
        protocol = EscalationProtocol()

        record = protocol.create_escalation(
            context={},
            severity="low",
        )

        # First decision
        protocol.capture_decision(
            escalation_id=record.id,
            selected_option="approve",
            reviewer="bob",
            rationale="First decision",
        )

        # Try to capture again
        with pytest.raises(ValueError, match="is not pending"):
            protocol.capture_decision(
                escalation_id=record.id,
                selected_option="reject",
                reviewer="alice",
                rationale="Second decision",
            )

    def test_get_escalation_history(self):
        """Test getting escalation history."""
        protocol = EscalationProtocol()

        # Create multiple escalations
        record1 = protocol.create_escalation(
            context={"type": "A"},
            severity="high",
            level=1,
        )
        record2 = protocol.create_escalation(
            context={"type": "B"},
            severity="low",
            level=2,
        )

        # Resolve one
        protocol.capture_decision(
            escalation_id=record1.id,
            selected_option="approve",
            reviewer="bob",
            rationale="Test",
        )

        # Get all history
        history = protocol.get_escalation_history()
        assert len(history) == 2

        # Filter by status
        resolved = protocol.get_escalation_history(filters={"status": "resolved"})
        assert len(resolved) == 1
        assert resolved[0].id == record1.id

        # Filter by level
        level_2 = protocol.get_escalation_history(filters={"level": 2})
        assert len(level_2) == 1
        assert level_2[0].id == record2.id

    def test_check_sla(self):
        """Test checking SLA status."""
        protocol = EscalationProtocol()

        record = protocol.create_escalation(
            context={},
            severity="critical",
            level=1,
        )

        sla_status = protocol.check_sla(record.id)

        assert sla_status.escalation_id == record.id
        assert sla_status.level == 1
        assert sla_status.time_remaining > 0
        assert sla_status.is_breached is False

    def test_check_sla_not_found(self):
        """Test checking SLA for non-existent escalation."""
        protocol = EscalationProtocol()

        with pytest.raises(KeyError, match="Escalation not found"):
            protocol.check_sla("ESC-NONEXISTENT")

    def test_check_all_slas(self):
        """Test checking SLA status for all escalations."""
        protocol = EscalationProtocol()

        # Create multiple escalations
        record1 = protocol.create_escalation(context={}, severity="high", level=1)
        record2 = protocol.create_escalation(context={}, severity="medium", level=2)

        # Resolve one
        protocol.capture_decision(
            escalation_id=record1.id,
            selected_option="approve",
            reviewer="bob",
            rationale="Test",
        )

        all_slas = protocol.check_all_slas()

        # Should only have SLA for pending escalation
        assert len(all_slas) == 1
        assert all_slas[0].escalation_id == record2.id

    def test_auto_escalate_breached(self):
        """Test auto-escalation on SLA breach."""
        # Create protocol with very short SLA for testing
        config = {
            "sla_durations": {
                1: timedelta(seconds=0.1),  # 100ms for testing
                2: timedelta(seconds=0.2),
                3: timedelta(seconds=0.3),
            }
        }
        protocol = EscalationProtocol(config=config)

        record = protocol.create_escalation(
            context={},
            severity="critical",
            level=1,
        )

        # Wait for SLA to breach
        time.sleep(0.15)

        # Check that SLA is breached
        sla_status = protocol.check_sla(record.id)
        assert sla_status.is_breached is True

        # Auto-escalate
        escalated = protocol.auto_escalate_breached()
        assert len(escalated) == 1

        # Verify escalation level increased
        updated = protocol.get_escalation(record.id)
        assert updated.escalation_level == 2

    def test_auto_escalate_to_expired(self):
        """Test that L3 escalations expire on breach."""
        config = {
            "sla_durations": {
                3: timedelta(seconds=0.1),
            }
        }
        protocol = EscalationProtocol(config=config)

        record = protocol.create_escalation(
            context={},
            severity="critical",
            level=3,
        )

        # Wait for SLA to breach
        time.sleep(0.15)

        # Auto-escalate
        escalated = protocol.auto_escalate_breached()
        assert len(escalated) == 1

        # Verify escalation expired
        updated = protocol.get_escalation(record.id)
        assert updated.status == EscalationStatus.EXPIRED

    def test_cancel_escalation(self):
        """Test cancelling an escalation."""
        protocol = EscalationProtocol()

        record = protocol.create_escalation(
            context={},
            severity="medium",
        )

        result = protocol.cancel_escalation(
            escalation_id=record.id,
            reason="No longer needed",
            cancelled_by="alice",
        )

        assert result is True

        updated = protocol.get_escalation(record.id)
        assert updated.status == EscalationStatus.CANCELLED
        assert updated.metadata["cancellation_reason"] == "No longer needed"
        assert updated.metadata["cancelled_by"] == "alice"

    def test_cancel_escalation_not_pending(self):
        """Test cancelling a non-pending escalation."""
        protocol = EscalationProtocol()

        record = protocol.create_escalation(context={}, severity="low")

        # First resolve it
        protocol.capture_decision(
            escalation_id=record.id,
            selected_option="approve",
            reviewer="bob",
            rationale="Test",
        )

        # Try to cancel
        with pytest.raises(ValueError, match="is not pending"):
            protocol.cancel_escalation(record.id, "No longer needed")

    def test_get_stats(self):
        """Test getting escalation statistics."""
        protocol = EscalationProtocol()

        # Create escalations with different levels and severities
        record1 = protocol.create_escalation(context={}, severity="high", level=1)
        record2 = protocol.create_escalation(context={}, severity="low", level=2)
        record3 = protocol.create_escalation(context={}, severity="critical", level=1)

        # Resolve one
        protocol.capture_decision(
            escalation_id=record1.id,
            selected_option="approve",
            reviewer="bob",
            rationale="Test",
        )

        stats = protocol.get_stats()

        assert stats["total"] == 3
        assert stats["by_status"]["pending"] == 2
        assert stats["by_status"]["resolved"] == 1
        assert stats["by_level"][1] == 2
        assert stats["by_level"][2] == 1
        assert stats["by_severity"]["high"] == 1
        assert stats["by_severity"]["low"] == 1
        assert stats["by_severity"]["critical"] == 1

    def test_thread_safety(self):
        """Test that protocol is thread-safe."""
        protocol = EscalationProtocol()
        errors = []
        records = []

        def create_and_resolve(i):
            try:
                record = protocol.create_escalation(
                    context={"thread": i},
                    severity="medium",
                )
                records.append(record.id)
                protocol.capture_decision(
                    escalation_id=record.id,
                    selected_option="approve",
                    reviewer=f"thread-{i}",
                    rationale=f"Decision from thread {i}",
                )
            except Exception as e:
                errors.append(e)

        # Run multiple threads
        threads = [threading.Thread(target=create_and_resolve, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify no errors
        assert len(errors) == 0
        assert len(records) == 10

        # Verify all records are resolved
        stats = protocol.get_stats()
        assert stats["total"] == 10
        assert stats["by_status"]["resolved"] == 10


class TestSLADurations:
    """Tests for SLA duration configuration."""

    def test_default_sla_durations(self):
        """Test default SLA durations are correct."""
        assert SLA_DURATIONS[1] == timedelta(minutes=15)
        assert SLA_DURATIONS[2] == timedelta(hours=1)
        assert SLA_DURATIONS[3] == timedelta(hours=4)

    def test_custom_sla_durations(self):
        """Test custom SLA durations."""
        config = {
            "sla_durations": {
                1: timedelta(minutes=5),
                2: timedelta(minutes=30),
            }
        }
        protocol = EscalationProtocol(config=config)

        record = protocol.create_escalation(context={}, severity="high", level=1)

        # Verify SLA deadline is approximately 5 minutes from now
        from src.utils.timezone import from_iso8601
        deadline = from_iso8601(record.sla_deadline)
        now = now_utc()
        diff = (deadline - now).total_seconds()

        # Should be close to 5 minutes (300 seconds)
        assert 290 < diff < 310


class TestSLAWarningThreshold:
    """Tests for SLA warning threshold."""

    def test_warning_threshold(self):
        """Test that warning is triggered at threshold."""
        # Create protocol with short SLA and 50% warning threshold
        config = {
            "sla_durations": {
                1: timedelta(seconds=1),
            },
            "warning_threshold": 0.5,
        }
        protocol = EscalationProtocol(config=config)

        record = protocol.create_escalation(context={}, severity="high", level=1)

        # Initially, no warning
        sla = protocol.check_sla(record.id)
        assert sla.is_warning is False

        # Wait for 50% of time to pass
        time.sleep(0.6)

        # Now should be in warning
        sla = protocol.check_sla(record.id)
        assert sla.is_warning is True


class TestFactoryFunction:
    """Tests for factory function."""

    def test_create_escalation_protocol_factory(self):
        """Test factory function creates protocol."""
        protocol = create_escalation_protocol()
        assert isinstance(protocol, EscalationProtocol)

    def test_create_escalation_protocol_with_config(self):
        """Test factory function with config."""
        config = {"auto_escalate": False}
        protocol = create_escalation_protocol(config=config)
        assert protocol._auto_escalate_enabled is False


class TestValidationCriteria:
    """Tests for validation criteria from implementation plan."""

    def test_criterion_escalation_created(self):
        """Validation: Escalation records created."""
        protocol = EscalationProtocol()

        record = protocol.create_escalation(
            context={"test": "data"},
            severity="high",
        )

        assert record.id is not None
        assert record.timestamp is not None
        assert record.status == EscalationStatus.PENDING
        assert record in protocol.get_escalation_history()

    def test_criterion_decision_captured(self):
        """Validation: Decisions captured correctly."""
        protocol = EscalationProtocol()

        options = [
            EscalationOption(id="approve", label="Approve", description="Approve"),
        ]

        record = protocol.create_escalation(
            context={},
            severity="medium",
            options=options,
        )

        protocol.capture_decision(
            escalation_id=record.id,
            selected_option="approve",
            reviewer="test_user",
            rationale="Test rationale",
        )

        updated = protocol.get_escalation(record.id)
        assert updated.selected_option == "approve"
        assert updated.reviewer == "test_user"
        assert updated.rationale == "Test rationale"
        assert updated.status == EscalationStatus.RESOLVED

    def test_criterion_sla_tracked(self):
        """Validation: SLA tracking works."""
        protocol = EscalationProtocol()

        record = protocol.create_escalation(
            context={},
            severity="critical",
            level=1,
        )

        sla = protocol.check_sla(record.id)

        assert sla.escalation_id == record.id
        assert sla.level == 1
        assert sla.deadline is not None
        assert sla.time_remaining > 0
        assert sla.is_breached is False

    def test_criterion_auto_escalation(self):
        """Validation: Auto-escalation triggers on SLA breach."""
        config = {
            "sla_durations": {
                1: timedelta(milliseconds=100),
                2: timedelta(milliseconds=100),
            }
        }
        protocol = EscalationProtocol(config=config)

        record = protocol.create_escalation(
            context={},
            severity="critical",
            level=1,
        )

        # Wait for breach
        time.sleep(0.2)

        # Verify breached
        sla = protocol.check_sla(record.id)
        assert sla.is_breached is True

        # Auto-escalate
        escalated = protocol.auto_escalate_breached()
        assert len(escalated) == 1

        updated = protocol.get_escalation(record.id)
        assert updated.escalation_level == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
