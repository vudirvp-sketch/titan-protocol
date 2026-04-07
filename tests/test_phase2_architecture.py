"""
Tests for PHASE_2 Architecture Critical Components.

ITEM-ARCH-02: EventJournal and RecoveryManager
ITEM-ARCH-03: LockBackend implementations
ITEM-ARCH-04: Gate-04 SEV-1 Override Fix
ITEM-ARCH-07: ApprovalLoop

Author: TITAN FUSE Team
Version: 3.3.0
"""

import pytest
import tempfile
import json
from pathlib import Path
from datetime import datetime
import time

# ITEM-ARCH-02 Tests
from src.state.event_journal import EventJournal, JournalEntry, JournalEntryType
from src.state.recovery import RecoveryManager, RecoveryStatus, RecoveryResult


class TestEventJournal:
    """Tests for EventJournal (ITEM-ARCH-02)."""
    
    def test_journal_creation(self, tmp_path):
        """Test journal creation."""
        journal_path = tmp_path / "test_journal.jsonl"
        journal = EventJournal(journal_path)
        
        assert journal.get_cursor() == 0
        assert journal.get_size_bytes() == 0
    
    def test_append_event(self, tmp_path):
        """Test appending events to journal."""
        journal_path = tmp_path / "test_journal.jsonl"
        journal = EventJournal(journal_path)
        
        # Append an event
        cursor = journal.append({
            "event_type": "TEST_EVENT",
            "data": {"key": "value"}
        })
        
        assert cursor == 1
        assert journal.get_cursor() == 1
        assert journal.get_size_bytes() > 0
    
    def test_replay_events(self, tmp_path):
        """Test replaying events from journal."""
        journal_path = tmp_path / "test_journal.jsonl"
        journal = EventJournal(journal_path)
        
        # Append multiple events
        for i in range(5):
            journal.append({
                "event_type": f"EVENT_{i}",
                "data": {"index": i}
            })
        
        # Replay all events
        events = journal.replay()
        assert len(events) == 5
        
        # Replay from specific cursor
        events = journal.replay(from_cursor=3)
        assert len(events) == 3
    
    def test_sync_vs_buffered_write(self, tmp_path):
        """Test synchronous vs buffered write behavior."""
        journal_path = tmp_path / "test_journal.jsonl"
        journal = EventJournal(journal_path)
        
        # Sync write (CRITICAL event)
        journal.append({"event_type": "GATE_FAIL", "data": {}}, sync=True)
        assert journal.get_cursor() == 1
        
        # Buffered write (INFO event)
        journal.append({"event_type": "INFO", "data": {}}, sync=False)
        assert journal.get_cursor() == 2
        
        # Flush buffer
        journal.sync_flush()
        events = journal.replay()
        assert len(events) == 2
    
    def test_compaction(self, tmp_path):
        """Test journal compaction."""
        journal_path = tmp_path / "test_journal.jsonl"
        journal = EventJournal(journal_path, max_size_mb=1)
        
        # Append many events
        for i in range(100):
            journal.append({
                "event_type": "EVENT",
                "data": {"index": i}
            })
        
        # Compact journal
        removed = journal.compact(checkpoint_cursor=50)
        assert removed == 50
        
        events = journal.replay()
        assert len(events) == 50


class TestRecoveryManager:
    """Tests for RecoveryManager (ITEM-ARCH-02)."""
    
    def test_no_recovery_needed(self, tmp_path):
        """Test when no journal exists."""
        journal_path = tmp_path / "nonexistent.jsonl"
        manager = RecoveryManager()
        
        result = manager.recover_from_journal(journal_path)
        
        assert result.status == RecoveryStatus.NO_RECOVERY_NEEDED
        assert result.events_replayed == 0
    
    def test_recovery_from_journal(self, tmp_path):
        """Test recovery from existing journal."""
        journal_path = tmp_path / "test_journal.jsonl"
        journal = EventJournal(journal_path)
        
        # Create some events
        journal.append({"event_type": "SESSION_START", "data": {"session_id": "test-123"}})
        journal.append({"event_type": "GATE_PASS", "data": {"gate_id": "GATE-01"}})
        journal.append({"event_type": "GATE_PASS", "data": {"gate_id": "GATE-02"}})
        
        # Recover
        manager = RecoveryManager()
        result = manager.recover_from_journal(journal_path)
        
        assert result.status == RecoveryStatus.SUCCESS
        assert result.events_replayed == 3
        assert result.state is not None
    
    def test_rebuild_state_from_events(self):
        """Test state rebuild from events."""
        manager = RecoveryManager()
        
        events = [
            {"event_type": "SESSION_START", "data": {"session_id": "test"}, "timestamp": "2024-01-01T00:00:00Z"},
            {"event_type": "GATE_PASS", "data": {"gate_id": "GATE-01"}, "timestamp": "2024-01-01T00:01:00Z"},
            {"event_type": "GATE_PASS", "data": {"gate_id": "GATE-02"}, "timestamp": "2024-01-01T00:02:00Z"},
            {"event_type": "GATE_FAIL", "data": {"gate_id": "GATE-03", "reason": "Test failure"}, "timestamp": "2024-01-01T00:03:00Z"},
        ]
        
        state = manager.rebuild_state_from_events(events)
        
        assert state["session_id"] == "test"
        assert state["gates"]["GATE-01"]["status"] == "PASS"
        assert state["gates"]["GATE-02"]["status"] == "PASS"
        assert state["gates"]["GATE-03"]["status"] == "FAIL"


# ITEM-ARCH-03 Tests
from src.locks.backend import Lock, LockStatus
from src.locks.file_lock import FileLockBackend
from src.locks.deadlock_detector import DeadlockDetector


class TestFileLockBackend:
    """Tests for FileLockBackend (ITEM-ARCH-03)."""
    
    def test_acquire_and_release(self, tmp_path):
        """Test basic acquire and release."""
        backend = FileLockBackend(tmp_path / "locks")
        
        # Acquire lock
        lock = backend.acquire("test_resource", ttl_seconds=60)
        assert lock is not None
        assert backend.is_locked("test_resource")
        
        # Release lock
        released = backend.release(lock)
        assert released
        assert not backend.is_locked("test_resource")
    
    def test_lock_contention(self, tmp_path):
        """Test lock contention behavior."""
        backend = FileLockBackend(tmp_path / "locks")
        
        # First lock
        lock1 = backend.acquire("shared_resource", ttl_seconds=60, owner="owner1")
        assert lock1 is not None
        
        # Second attempt should fail
        lock2 = backend.acquire("shared_resource", ttl_seconds=60, owner="owner2")
        assert lock2 is None
        
        # Release first lock
        backend.release(lock1)
        
        # Now second should succeed
        lock2 = backend.acquire("shared_resource", ttl_seconds=60, owner="owner2")
        assert lock2 is not None
        
        backend.release(lock2)
    
    def test_lock_ttl_expiration(self, tmp_path):
        """Test TTL expiration."""
        backend = FileLockBackend(tmp_path / "locks")
        
        # Acquire with short TTL
        lock = backend.acquire("ttl_resource", ttl_seconds=1)
        assert lock is not None
        
        # Wait for expiration
        time.sleep(1.5)
        
        # Lock should be expired
        assert not backend.is_locked("ttl_resource")
        
        # Should be able to acquire now
        new_lock = backend.acquire("ttl_resource", ttl_seconds=60)
        assert new_lock is not None
    
    def test_extend_lock(self, tmp_path):
        """Test extending lock TTL."""
        backend = FileLockBackend(tmp_path / "locks")
        
        lock = backend.acquire("extend_resource", ttl_seconds=2)
        assert lock is not None
        
        # Extend TTL
        extended = backend.extend(lock, ttl_seconds=60)
        assert extended
        
        # Wait for original TTL
        time.sleep(2.5)
        
        # Should still be locked due to extension
        assert backend.is_locked("extend_resource")
        
        backend.release(lock)
    
    def test_cleanup_stale(self, tmp_path):
        """Test stale lock cleanup."""
        backend = FileLockBackend(tmp_path / "locks")
        
        # Create some locks
        lock1 = backend.acquire("resource1", ttl_seconds=1)
        lock2 = backend.acquire("resource2", ttl_seconds=60)
        
        # Wait for first to expire
        time.sleep(1.5)
        
        # Cleanup stale
        cleaned = backend.cleanup_stale()
        assert cleaned >= 1
        
        # Check remaining
        assert not backend.is_locked("resource1")
        assert backend.is_locked("resource2")
        
        backend.release(lock2)


class TestDeadlockDetector:
    """Tests for DeadlockDetector (ITEM-ARCH-03)."""
    
    def test_no_deadlock(self):
        """Test when no deadlock exists."""
        detector = DeadlockDetector()
        
        detector.record_acquire("owner1", "resource_a")
        detector.record_acquire("owner2", "resource_b")
        
        deadlock = detector.detect_deadlock()
        assert deadlock is None
    
    def test_deadlock_detection(self):
        """Test deadlock detection."""
        detector = DeadlockDetector()
        
        # Create a simple deadlock scenario
        detector.record_acquire("owner1", "resource_a")
        detector.record_acquire("owner2", "resource_b")
        
        # owner1 waits for resource_b (owned by owner2)
        detector.record_wait("owner1", "resource_b")
        
        # owner2 waits for resource_a (owned by owner1) - DEADLOCK!
        detector.record_wait("owner2", "resource_a")
        
        deadlock = detector.detect_deadlock()
        assert deadlock is not None
        assert len(deadlock.cycle) > 0
    
    def test_wait_graph(self):
        """Test wait graph generation."""
        detector = DeadlockDetector()
        
        detector.record_acquire("owner1", "resource_a")
        detector.record_wait("owner2", "resource_a")
        
        graph = detector.get_wait_graph()
        
        assert "owner2" in graph["nodes"]
        assert "owner1" in graph["nodes"]
        assert len(graph["edges"]) == 1


# ITEM-ARCH-04 Tests
from src.policy.gate_evaluation import (
    Gate04Evaluator, GateResult, Gap, Severity, 
    evaluate_gate_04
)


class TestGate04Evaluator:
    """Tests for Gate04Evaluator (ITEM-ARCH-04)."""
    
    def test_pass_with_no_gaps(self):
        """Test pass with no gaps."""
        evaluator = Gate04Evaluator()
        result = evaluator.evaluate([])
        
        assert result.result == GateResult.PASS
        assert "passed" in result.reason.lower()
    
    def test_sev1_always_blocks(self):
        """Test that SEV-1 gaps always block."""
        evaluator = Gate04Evaluator()
        
        gaps = [
            Gap(gap_id="gap1", severity=Severity.SEV_1, description="Critical issue"),
        ]
        
        # Even with HIGH confidence, SEV-1 should block
        result = evaluator.evaluate(gaps, confidence="HIGH")
        
        assert result.result == GateResult.FAIL
        assert "SEV-1" in result.reason
    
    def test_sev2_threshold_blocks(self):
        """Test that SEV-2 gaps block when above threshold."""
        evaluator = Gate04Evaluator({"gate04": {"max_sev2_gaps": 1}})
        
        gaps = [
            Gap(gap_id="gap1", severity=Severity.SEV_2),
            Gap(gap_id="gap2", severity=Severity.SEV_2),
        ]
        
        result = evaluator.evaluate(gaps, confidence="HIGH")
        
        assert result.result == GateResult.FAIL
        assert "SEV-2" in result.reason
    
    def test_sev3_sev4_advisory_pass(self):
        """Test advisory pass for SEV-3/SEV-4 with HIGH confidence."""
        evaluator = Gate04Evaluator({"gate04_confidence_override": True})
        
        gaps = [
            Gap(gap_id="gap1", severity=Severity.SEV_3, description="Minor issue"),
            Gap(gap_id="gap2", severity=Severity.SEV_4, description="Info issue"),
        ]
        
        result = evaluator.evaluate(gaps, confidence="HIGH")
        
        assert result.result == GateResult.ADVISORY_PASS
        assert len(result.advisory_warnings) == 2
    
    def test_resolved_gaps_ignored(self):
        """Test that resolved gaps are ignored."""
        evaluator = Gate04Evaluator()
        
        gaps = [
            Gap(gap_id="gap1", severity=Severity.SEV_1, resolved=True),
        ]
        
        result = evaluator.evaluate(gaps)
        
        assert result.result == GateResult.PASS
    
    def test_advisory_misapplication_check(self):
        """Test detection of advisory misapplication."""
        evaluator = Gate04Evaluator()
        
        gaps = [
            Gap(gap_id="gap1", severity=Severity.SEV_1),
        ]
        
        error = evaluator.check_advisory_misapplication(gaps, "HIGH")
        
        assert error is not None
        assert "misapplied" in error.lower()


# ITEM-ARCH-07 Tests
from src.approval.loop import (
    ApprovalLoop, ApprovalStatus, CursorDriftError
)


class TestApprovalLoop:
    """Tests for ApprovalLoop (ITEM-ARCH-07)."""
    
    def test_cursor_hash_computation(self):
        """Test cursor hash computation."""
        loop = ApprovalLoop(agent_id="test-agent")
        
        state1 = {"key": "value", "nested": {"a": 1}}
        state2 = {"key": "value", "nested": {"a": 2}}
        
        hash1 = loop.compute_cursor_hash(state1)
        hash2 = loop.compute_cursor_hash(state2)
        
        assert hash1 != hash2
        assert len(hash1) == 64  # SHA-256
    
    def test_cursor_validation(self):
        """Test cursor validation."""
        loop = ApprovalLoop(agent_id="test-agent")
        
        state = {"key": "value"}
        original_hash = loop.compute_cursor_hash(state)
        loop._last_cursor_hash = original_hash
        
        # Same state should validate
        assert loop.validate_cursor(state)
        
        # Different state should fail
        loop._last_cursor_hash = original_hash
        different_state = {"key": "different"}
        assert not loop.validate_cursor(different_state)
    
    def test_lock_registration(self):
        """Test lock registration."""
        loop = ApprovalLoop(agent_id="test-agent")
        
        class MockLock:
            pass
        
        lock = MockLock()
        loop.register_lock("resource_a", lock)
        
        assert "resource_a" in loop.get_held_locks()
        assert loop.get_held_locks()["resource_a"] is lock
    
    def test_emit_review_checkpoint(self):
        """Test review checkpoint emission."""
        loop = ApprovalLoop(agent_id="test-agent")
        
        state = {"session_id": "test-123"}
        cursor_hash = loop.emit_review_checkpoint(state)
        
        assert cursor_hash is not None
        assert loop._last_cursor_hash == cursor_hash
    
    def test_cursor_drift_error(self):
        """Test cursor drift error."""
        expected = "a" * 64
        actual = "b" * 64
        
        error = CursorDriftError(expected, actual)
        
        assert error.expected_hash == expected
        assert error.actual_hash == actual
        assert "external_modification_during_wait" in str(error)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
