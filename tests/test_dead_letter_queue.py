"""
Tests for ITEM-RESILIENCE-01: Dead Letter Queue (DLQ)

This module tests the Dead Letter Queue implementation for resilient
event handling with retry policies and persistent storage.

Author: TITAN FUSE Team
Version: 3.4.0
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch
from dataclasses import asdict

from src.events.dead_letter_queue import (
    DeadLetterQueue,
    FailedEvent,
    RetryPolicy,
    RetryResult,
    DLQStats,
)
from src.events.event_bus import Event, EventSeverity


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_storage():
    """Create a mock storage backend for testing."""
    storage = MagicMock()
    storage.save_json = MagicMock()
    storage.load_json = MagicMock(return_value={})
    storage.delete = MagicMock()
    storage.list = MagicMock(return_value=[])
    return storage


@pytest.fixture
def retry_policy():
    """Create a default retry policy for testing."""
    return RetryPolicy(
        max_retries=3,
        base_delay_ms=1000,
        exponential_backoff=True
    )


@pytest.fixture
def sample_event():
    """Create a sample event for testing."""
    return Event(
        event_type="TEST_EVENT",
        data={"key": "value"},
        severity=EventSeverity.INFO,
        source="test_source"
    )


@pytest.fixture
def sample_error():
    """Create a sample error for testing."""
    return ValueError("Test error message")


@pytest.fixture
def dlq(mock_storage, retry_policy):
    """Create a DeadLetterQueue instance for testing."""
    return DeadLetterQueue(
        storage_backend=mock_storage,
        retry_policy=retry_policy,
        session_id="test-session"
    )


# =============================================================================
# Test RetryPolicy
# =============================================================================

class TestRetryPolicy:
    """Tests for RetryPolicy dataclass."""

    def test_default_values(self):
        """Test default retry policy values."""
        policy = RetryPolicy()
        assert policy.max_retries == 3
        assert policy.base_delay_ms == 1000
        assert policy.exponential_backoff is True

    def test_custom_values(self):
        """Test custom retry policy values."""
        policy = RetryPolicy(
            max_retries=5,
            base_delay_ms=500,
            exponential_backoff=False
        )
        assert policy.max_retries == 5
        assert policy.base_delay_ms == 500
        assert policy.exponential_backoff is False

    def test_get_delay_ms_no_backoff(self):
        """Test delay calculation without exponential backoff."""
        policy = RetryPolicy(base_delay_ms=1000, exponential_backoff=False)
        assert policy.get_delay_ms(0) == 1000
        assert policy.get_delay_ms(1) == 1000
        assert policy.get_delay_ms(5) == 1000

    def test_get_delay_ms_exponential_backoff(self):
        """Test delay calculation with exponential backoff."""
        policy = RetryPolicy(base_delay_ms=1000, exponential_backoff=True)
        assert policy.get_delay_ms(0) == 1000  # 1000 * 2^0
        assert policy.get_delay_ms(1) == 2000  # 1000 * 2^1
        assert policy.get_delay_ms(2) == 4000  # 1000 * 2^2
        assert policy.get_delay_ms(3) == 8000  # 1000 * 2^3

    def test_get_delay_ms_cap_at_60_seconds(self):
        """Test that delay is capped at 60 seconds."""
        policy = RetryPolicy(base_delay_ms=1000, exponential_backoff=True)
        # 2^10 = 1024, so 1000 * 1024 = 1024000ms > 60000ms
        assert policy.get_delay_ms(10) == 60000
        assert policy.get_delay_ms(20) == 60000

    def test_to_dict(self):
        """Test RetryPolicy serialization to dictionary."""
        policy = RetryPolicy(max_retries=5, base_delay_ms=2000)
        d = policy.to_dict()
        assert d["max_retries"] == 5
        assert d["base_delay_ms"] == 2000
        assert d["exponential_backoff"] is True

    def test_from_dict(self):
        """Test RetryPolicy deserialization from dictionary."""
        d = {"max_retries": 4, "base_delay_ms": 500, "exponential_backoff": False}
        policy = RetryPolicy.from_dict(d)
        assert policy.max_retries == 4
        assert policy.base_delay_ms == 500
        assert policy.exponential_backoff is False


# =============================================================================
# Test RetryResult
# =============================================================================

class TestRetryResult:
    """Tests for RetryResult dataclass."""

    def test_success_result(self):
        """Test successful retry result."""
        result = RetryResult(success=True, event_id="evt-123")
        assert result.success is True
        assert result.event_id == "evt-123"
        assert result.error_message is None

    def test_failure_result(self):
        """Test failed retry result."""
        result = RetryResult(
            success=False,
            event_id="evt-123",
            error_message="Max retries exceeded"
        )
        assert result.success is False
        assert result.error_message == "Max retries exceeded"

    def test_to_dict(self):
        """Test RetryResult serialization."""
        result = RetryResult(success=True, event_id="evt-123")
        d = result.to_dict()
        assert d["success"] is True
        assert d["event_id"] == "evt-123"
        assert d["error_message"] is None

    def test_from_dict(self):
        """Test RetryResult deserialization."""
        d = {"success": False, "event_id": "evt-456", "error_message": "Not found"}
        result = RetryResult.from_dict(d)
        assert result.success is False
        assert result.event_id == "evt-456"
        assert result.error_message == "Not found"


# =============================================================================
# Test DLQStats
# =============================================================================

class TestDLQStats:
    """Tests for DLQStats dataclass."""

    def test_default_values(self):
        """Test default DLQStats values."""
        stats = DLQStats()
        assert stats.total_events == 0
        assert stats.pending_retry == 0
        assert stats.permanently_failed == 0
        assert stats.by_severity == {}
        assert stats.oldest_event_age_hours is None
        assert stats.total_retries == 0
        assert stats.successful_retries == 0

    def test_custom_values(self):
        """Test custom DLQStats values."""
        stats = DLQStats(
            total_events=10,
            pending_retry=5,
            permanently_failed=5,
            by_severity={"INFO": 6, "WARN": 4},
            oldest_event_age_hours=24.5,
            total_retries=20,
            successful_retries=15
        )
        assert stats.total_events == 10
        assert stats.pending_retry == 5
        assert stats.by_severity == {"INFO": 6, "WARN": 4}

    def test_to_dict(self):
        """Test DLQStats serialization."""
        stats = DLQStats(total_events=5, pending_retry=3)
        d = stats.to_dict()
        assert d["total_events"] == 5
        assert d["pending_retry"] == 3

    def test_from_dict(self):
        """Test DLQStats deserialization."""
        d = {
            "total_events": 8,
            "pending_retry": 4,
            "permanently_failed": 4,
            "by_severity": {"CRITICAL": 2, "WARN": 6},
            "oldest_event_age_hours": 12.0,
            "total_retries": 10,
            "successful_retries": 6
        }
        stats = DLQStats.from_dict(d)
        assert stats.total_events == 8
        assert stats.by_severity == {"CRITICAL": 2, "WARN": 6}


# =============================================================================
# Test FailedEvent
# =============================================================================

class TestFailedEvent:
    """Tests for FailedEvent dataclass."""

    def test_create_failed_event(self, sample_event):
        """Test creating a FailedEvent instance."""
        failed = FailedEvent(
            event_id="dlq-test123",
            original_event=sample_event,
            error_type="ValueError",
            error_message="Test error",
            traceback="Traceback...",
            retry_count=0,
            max_retries=3,
            first_failed_at="2024-01-01T00:00:00Z",
            last_failed_at="2024-01-01T00:00:00Z",
            context={"handler": "test_handler"}
        )
        assert failed.event_id == "dlq-test123"
        assert failed.error_type == "ValueError"
        assert failed.retry_count == 0
        assert failed.max_retries == 3

    def test_can_retry_when_below_max(self, sample_event):
        """Test can_retry returns True when below max retries."""
        failed = FailedEvent(
            event_id="dlq-test",
            original_event=sample_event,
            error_type="ValueError",
            error_message="Error",
            traceback="",
            retry_count=0,
            max_retries=3,
            first_failed_at="2024-01-01T00:00:00Z",
            last_failed_at="2024-01-01T00:00:00Z"
        )
        assert failed.can_retry() is True

    def test_can_retry_when_at_max(self, sample_event):
        """Test can_retry returns False when at max retries."""
        failed = FailedEvent(
            event_id="dlq-test",
            original_event=sample_event,
            error_type="ValueError",
            error_message="Error",
            traceback="",
            retry_count=3,
            max_retries=3,
            first_failed_at="2024-01-01T00:00:00Z",
            last_failed_at="2024-01-01T00:00:00Z"
        )
        assert failed.can_retry() is False

    def test_can_retry_when_exceeded(self, sample_event):
        """Test can_retry returns False when retries exceeded."""
        failed = FailedEvent(
            event_id="dlq-test",
            original_event=sample_event,
            error_type="ValueError",
            error_message="Error",
            traceback="",
            retry_count=5,
            max_retries=3,
            first_failed_at="2024-01-01T00:00:00Z",
            last_failed_at="2024-01-01T00:00:00Z"
        )
        assert failed.can_retry() is False

    def test_to_dict(self, sample_event):
        """Test FailedEvent serialization to dictionary."""
        failed = FailedEvent(
            event_id="dlq-test",
            original_event=sample_event,
            error_type="ValueError",
            error_message="Test error",
            traceback="Traceback...",
            retry_count=1,
            max_retries=3,
            first_failed_at="2024-01-01T00:00:00Z",
            last_failed_at="2024-01-01T01:00:00Z",
            context={"key": "value"}
        )
        d = failed.to_dict()
        assert d["event_id"] == "dlq-test"
        assert d["error_type"] == "ValueError"
        assert d["retry_count"] == 1
        assert d["max_retries"] == 3
        assert d["context"] == {"key": "value"}
        assert "original_event" in d

    def test_from_dict(self, sample_event):
        """Test FailedEvent deserialization from dictionary."""
        d = {
            "event_id": "dlq-restore",
            "original_event": sample_event.to_dict(),
            "error_type": "RuntimeError",
            "error_message": "Runtime issue",
            "traceback": "Stack trace...",
            "retry_count": 2,
            "max_retries": 5,
            "first_failed_at": "2024-01-01T00:00:00Z",
            "last_failed_at": "2024-01-01T02:00:00Z",
            "context": {"attempt": 2}
        }
        failed = FailedEvent.from_dict(d)
        assert failed.event_id == "dlq-restore"
        assert failed.error_type == "RuntimeError"
        assert failed.retry_count == 2
        assert failed.max_retries == 5
        assert failed.original_event.event_type == "TEST_EVENT"


# =============================================================================
# Test DeadLetterQueue
# =============================================================================

class TestDeadLetterQueue:
    """Tests for DeadLetterQueue class."""

    def test_initialization(self, mock_storage, retry_policy):
        """Test DLQ initialization."""
        dlq = DeadLetterQueue(
            storage_backend=mock_storage,
            retry_policy=retry_policy,
            session_id="test-session"
        )
        assert dlq._session_id == "test-session"
        assert dlq._retry_policy.max_retries == 3

    def test_enqueue(self, dlq, sample_event, sample_error):
        """Test adding a failed event to the queue."""
        event_id = dlq.enqueue(
            event=sample_event,
            error=sample_error,
            context={"handler": "test"}
        )
        assert event_id.startswith("dlq-")
        assert len(dlq) == 1
        assert event_id in dlq

    def test_enqueue_stores_to_storage(self, dlq, sample_event, sample_error, mock_storage):
        """Test that enqueue persists event to storage."""
        dlq.enqueue(sample_event, sample_error, {"handler": "test"})
        assert mock_storage.save_json.called

    def test_dequeue(self, dlq, sample_event, sample_error):
        """Test removing an event from the queue."""
        event_id = dlq.enqueue(sample_event, sample_error, {})
        
        failed_event = dlq.dequeue(event_id)
        
        assert failed_event is not None
        assert failed_event.event_id == event_id
        assert len(dlq) == 0
        assert event_id not in dlq

    def test_dequeue_nonexistent(self, dlq):
        """Test dequeue with nonexistent event ID."""
        result = dlq.dequeue("nonexistent-id")
        assert result is None

    def test_retry_success(self, dlq, sample_event, sample_error):
        """Test successful retry attempt."""
        event_id = dlq.enqueue(sample_event, sample_error, {})
        
        result = dlq.retry(event_id)
        
        assert result.success is True
        assert result.event_id == event_id
        assert result.error_message is None
        
        # Check retry count was incremented
        failed_event = dlq.get_event(event_id)
        assert failed_event.retry_count == 1

    def test_retry_nonexistent_event(self, dlq):
        """Test retry with nonexistent event ID."""
        result = dlq.retry("nonexistent-id")
        assert result.success is False
        assert "not found" in result.error_message.lower()

    def test_retry_exceeds_max(self, dlq, sample_event, sample_error):
        """Test retry when max retries exceeded."""
        event_id = dlq.enqueue(sample_event, sample_error, {})
        
        # Exhaust retries
        for _ in range(3):
            dlq.retry(event_id)
        
        # Next retry should fail
        result = dlq.retry(event_id)
        assert result.success is False
        assert "exceeded max retries" in result.error_message.lower()

    def test_mark_retry_success(self, dlq, sample_event, sample_error):
        """Test marking a retry as successful."""
        event_id = dlq.enqueue(sample_event, sample_error, {})
        
        result = dlq.mark_retry_success(event_id)
        
        assert result is True
        assert len(dlq) == 0

    def test_get_failed_events(self, dlq, sample_event, sample_error):
        """Test getting all failed events."""
        dlq.enqueue(sample_event, sample_error, {})
        
        # Create a CRITICAL event
        critical_event = Event(
            event_type="CRITICAL_EVENT",
            data={},
            severity=EventSeverity.CRITICAL
        )
        dlq.enqueue(critical_event, sample_error, {})
        
        events = dlq.get_failed_events()
        assert len(events) == 2

    def test_get_failed_events_by_severity(self, dlq, sample_event, sample_error):
        """Test filtering failed events by severity."""
        dlq.enqueue(sample_event, sample_error, {})  # INFO
        
        critical_event = Event(
            event_type="CRITICAL_EVENT",
            data={},
            severity=EventSeverity.CRITICAL
        )
        dlq.enqueue(critical_event, sample_error, {})
        
        # Filter by CRITICAL
        critical_events = dlq.get_failed_events(severity=EventSeverity.CRITICAL)
        assert len(critical_events) == 1
        assert critical_events[0].original_event.severity == EventSeverity.CRITICAL

    def test_get_event(self, dlq, sample_event, sample_error):
        """Test getting a specific event by ID."""
        event_id = dlq.enqueue(sample_event, sample_error, {})
        
        failed_event = dlq.get_event(event_id)
        
        assert failed_event is not None
        assert failed_event.event_id == event_id

    def test_get_event_nonexistent(self, dlq):
        """Test getting a nonexistent event."""
        result = dlq.get_event("nonexistent-id")
        assert result is None

    def test_purge_by_age(self, dlq, sample_event, sample_error):
        """Test purging old events by age."""
        # Add an event
        event_id = dlq.enqueue(sample_event, sample_error, {})
        
        # Manually set the last_failed_at to be old
        old_time = (datetime.utcnow() - timedelta(hours=48)).isoformat() + "Z"
        dlq._failed_events[event_id].last_failed_at = old_time
        dlq._failed_events[event_id].first_failed_at = old_time
        
        # Purge events older than 24 hours
        purged_count = dlq.purge(max_age_hours=24)
        
        assert purged_count == 1
        assert len(dlq) == 0

    def test_purge_keeps_recent_events(self, dlq, sample_event, sample_error):
        """Test that purge keeps recent events."""
        dlq.enqueue(sample_event, sample_error, {})
        
        # Purge events older than 24 hours (should not affect recent events)
        purged_count = dlq.purge(max_age_hours=24)
        
        assert purged_count == 0
        assert len(dlq) == 1

    def test_get_stats(self, dlq, sample_event, sample_error):
        """Test getting DLQ statistics."""
        dlq.enqueue(sample_event, sample_error, {})
        
        critical_event = Event(
            event_type="CRITICAL_EVENT",
            data={},
            severity=EventSeverity.CRITICAL
        )
        dlq.enqueue(critical_event, sample_error, {})
        
        stats = dlq.get_stats()
        
        assert stats.total_events == 2
        assert stats.pending_retry == 2
        assert "INFO" in stats.by_severity
        assert "CRITICAL" in stats.by_severity

    def test_get_stats_with_permanently_failed(self, dlq, sample_event, sample_error):
        """Test stats with permanently failed events."""
        event_id = dlq.enqueue(sample_event, sample_error, {})
        
        # Exhaust retries
        for _ in range(4):
            dlq.retry(event_id)
        
        stats = dlq.get_stats()
        
        assert stats.total_events == 1
        assert stats.permanently_failed == 1
        assert stats.pending_retry == 0

    def test_clear(self, dlq, sample_event, sample_error):
        """Test clearing all events from the queue."""
        dlq.enqueue(sample_event, sample_error, {})
        dlq.enqueue(sample_event, sample_error, {})
        
        count = dlq.clear()
        
        assert count == 2
        assert len(dlq) == 0

    def test_len(self, dlq, sample_event, sample_error):
        """Test __len__ method."""
        assert len(dlq) == 0
        
        dlq.enqueue(sample_event, sample_error, {})
        assert len(dlq) == 1
        
        dlq.enqueue(sample_event, sample_error, {})
        assert len(dlq) == 2

    def test_contains(self, dlq, sample_event, sample_error):
        """Test __contains__ method."""
        event_id = dlq.enqueue(sample_event, sample_error, {})
        
        assert event_id in dlq
        assert "nonexistent-id" not in dlq


# =============================================================================
# Integration Tests
# =============================================================================

class TestDeadLetterQueueIntegration:
    """Integration tests for DeadLetterQueue."""

    def test_full_retry_workflow(self, mock_storage, sample_event, sample_error):
        """Test complete workflow: enqueue, retry, succeed."""
        policy = RetryPolicy(max_retries=3)
        dlq = DeadLetterQueue(mock_storage, policy)
        
        # Enqueue
        event_id = dlq.enqueue(sample_event, sample_error, {"handler": "test"})
        assert event_id in dlq
        
        # Multiple retries
        for i in range(3):
            result = dlq.retry(event_id)
            assert result.success is True
            failed = dlq.get_event(event_id)
            assert failed.retry_count == i + 1
        
        # Mark as successful
        dlq.mark_retry_success(event_id)
        assert event_id not in dlq

    def test_retry_exhaustion_workflow(self, mock_storage, sample_event, sample_error):
        """Test workflow where retries are exhausted."""
        policy = RetryPolicy(max_retries=2)
        dlq = DeadLetterQueue(mock_storage, policy)
        
        event_id = dlq.enqueue(sample_event, sample_error, {})
        
        # Retry until exhausted
        dlq.retry(event_id)
        dlq.retry(event_id)
        result = dlq.retry(event_id)  # Should fail
        
        assert result.success is False
        failed = dlq.get_event(event_id)
        assert failed.can_retry() is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
