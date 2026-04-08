"""
Tests for ITEM-ARCH-10: PolicyStagingZone

This module tests the PolicyStagingZone implementation for holding
tentative policy decisions until clarity threshold is reached.

Author: TITAN FUSE Team
Version: 1.0.0
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch

from src.policy.staging_zone import (
    PolicyStagingZone,
    StagedPolicy,
    StagingZoneConfig,
    NoStagedPolicyError,
    InsufficientClarityError,
    StagedPolicyExpiredError,
    create_staging_zone,
    get_staging_zone,
    reset_staging_zone,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def staging_zone():
    """Create a default PolicyStagingZone for testing."""
    return PolicyStagingZone()


@pytest.fixture
def configured_staging_zone():
    """Create a configured PolicyStagingZone for testing."""
    config = StagingZoneConfig(
        min_confidence=0.6,
        max_staged=10,
        ttl_seconds=60,
        cleanup_interval_seconds=10
    )
    return PolicyStagingZone(config=config)


@pytest.fixture
def mock_event_bus():
    """Create a mock EventBus for testing."""
    return Mock()


@pytest.fixture
def mock_policy_engine():
    """Create a mock PolicyEngine for testing."""
    engine = Mock()
    engine.activate = Mock(return_value="activated_policy_id")
    return engine


@pytest.fixture
def staging_zone_with_deps(mock_policy_engine, mock_event_bus):
    """Create a PolicyStagingZone with mock dependencies."""
    return PolicyStagingZone(
        policy_engine=mock_policy_engine,
        event_bus=mock_event_bus
    )


# =============================================================================
# Test StagingZoneConfig
# =============================================================================

class TestStagingZoneConfig:
    """Tests for StagingZoneConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = StagingZoneConfig()
        assert config.min_confidence == 0.6
        assert config.max_staged == 100
        assert config.ttl_seconds == 3600
        assert config.cleanup_interval_seconds == 300

    def test_custom_config(self):
        """Test custom configuration values."""
        config = StagingZoneConfig(
            min_confidence=0.8,
            max_staged=50,
            ttl_seconds=1800,
            cleanup_interval_seconds=60
        )
        assert config.min_confidence == 0.8
        assert config.max_staged == 50
        assert config.ttl_seconds == 1800
        assert config.cleanup_interval_seconds == 60

    def test_from_dict(self):
        """Test creating config from dictionary."""
        config = StagingZoneConfig.from_dict({
            "min_confidence": 0.7,
            "max_staged": 75,
            "ttl_seconds": 7200
        })
        assert config.min_confidence == 0.7
        assert config.max_staged == 75
        assert config.ttl_seconds == 7200
        assert config.cleanup_interval_seconds == 300  # Default

    def test_from_dict_defaults(self):
        """Test creating config from empty dictionary."""
        config = StagingZoneConfig.from_dict({})
        assert config.min_confidence == 0.6
        assert config.max_staged == 100


# =============================================================================
# Test StagedPolicy
# =============================================================================

class TestStagedPolicy:
    """Tests for StagedPolicy dataclass."""

    def test_create_staged_policy(self):
        """Test creating a StagedPolicy instance."""
        policy = StagedPolicy(
            intent="code_review",
            policy_id="security_scan",
            confidence=0.5
        )
        assert policy.intent == "code_review"
        assert policy.policy_id == "security_scan"
        assert policy.confidence == 0.5
        assert policy.staged_id.startswith("staged-")

    def test_staged_policy_default_expiration(self):
        """Test that default expiration is set."""
        policy = StagedPolicy(
            intent="code_review",
            policy_id="security_scan",
            confidence=0.5
        )
        assert policy.expires_at > policy.staged_at
        # Default TTL is 1 hour
        expected = policy.staged_at + timedelta(hours=1)
        assert abs((policy.expires_at - expected).total_seconds()) < 1

    def test_staged_policy_custom_expiration(self):
        """Test custom expiration time."""
        expires = datetime.utcnow() + timedelta(minutes=30)
        policy = StagedPolicy(
            intent="code_review",
            policy_id="security_scan",
            confidence=0.5,
            expires_at=expires
        )
        assert policy.expires_at == expires

    def test_staged_policy_confidence_clamp(self):
        """Test that confidence is clamped to valid range."""
        policy = StagedPolicy(
            intent="test",
            policy_id="test",
            confidence=1.5
        )
        assert policy.confidence == 1.0

        policy = StagedPolicy(
            intent="test",
            policy_id="test",
            confidence=-0.5
        )
        assert policy.confidence == 0.0

    def test_is_expired(self):
        """Test expiration check."""
        # Not expired
        policy = StagedPolicy(
            intent="test",
            policy_id="test",
            confidence=0.5,
            expires_at=datetime.utcnow() + timedelta(hours=1)
        )
        assert policy.is_expired() is False

        # Expired
        policy = StagedPolicy(
            intent="test",
            policy_id="test",
            confidence=0.5,
            expires_at=datetime.utcnow() - timedelta(seconds=1)
        )
        assert policy.is_expired() is True

    def test_is_commitable(self):
        """Test commitable check."""
        # Commitable: not expired, confidence >= threshold
        policy = StagedPolicy(
            intent="test",
            policy_id="test",
            confidence=0.7,
            expires_at=datetime.utcnow() + timedelta(hours=1)
        )
        assert policy.is_commitable(0.6) is True
        assert policy.is_commitable(0.8) is False

        # Not commitable: expired
        policy = StagedPolicy(
            intent="test",
            policy_id="test",
            confidence=0.7,
            expires_at=datetime.utcnow() - timedelta(seconds=1)
        )
        assert policy.is_commitable(0.6) is False

    def test_to_dict(self):
        """Test serialization to dictionary."""
        policy = StagedPolicy(
            intent="code_review",
            policy_id="security_scan",
            confidence=0.5
        )
        d = policy.to_dict()
        assert d["intent"] == "code_review"
        assert d["policy_id"] == "security_scan"
        assert d["confidence"] == 0.5
        assert "staged_at" in d
        assert "expires_at" in d
        assert "is_expired" in d
        assert "is_commitable" in d

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "staged_id": "staged-abc123",
            "intent": "code_review",
            "policy_id": "security_scan",
            "confidence": 0.5,
            "staged_at": "2024-01-01T12:00:00Z",
            "expires_at": "2024-01-01T13:00:00Z",
            "metadata": {"key": "value"}
        }
        policy = StagedPolicy.from_dict(data)
        assert policy.staged_id == "staged-abc123"
        assert policy.intent == "code_review"
        assert policy.policy_id == "security_scan"
        assert policy.confidence == 0.5
        assert policy.metadata == {"key": "value"}


# =============================================================================
# Test Exception Classes
# =============================================================================

class TestExceptions:
    """Tests for exception classes."""

    def test_no_staged_policy_error(self):
        """Test NoStagedPolicyError exception."""
        error = NoStagedPolicyError("code_review")
        assert error.intent == "code_review"
        assert "code_review" in str(error)

    def test_no_staged_policy_error_custom_message(self):
        """Test NoStagedPolicyError with custom message."""
        error = NoStagedPolicyError("code_review", "Custom error message")
        assert error.message == "Custom error message"

    def test_insufficient_clarity_error(self):
        """Test InsufficientClarityError exception."""
        error = InsufficientClarityError(0.4, 0.6)
        assert error.confidence == 0.4
        assert error.min_confidence == 0.6
        assert "0.4" in str(error)
        assert "0.6" in str(error)

    def test_staged_policy_expired_error(self):
        """Test StagedPolicyExpiredError exception."""
        expired_at = datetime(2024, 1, 1, 12, 0, 0)
        error = StagedPolicyExpiredError("code_review", expired_at)
        assert error.intent == "code_review"
        assert error.expired_at == expired_at
        assert "code_review" in str(error)


# =============================================================================
# Test PolicyStagingZone.stage_policy()
# =============================================================================

class TestStagePolicy:
    """Tests for PolicyStagingZone.stage_policy() method."""

    def test_stage_policy_basic(self, staging_zone):
        """Test basic policy staging."""
        staged_id = staging_zone.stage_policy(
            intent="code_review",
            policy_id="security_scan",
            confidence=0.5
        )
        assert staged_id.startswith("staged-")

        # Verify policy was stored
        staged = staging_zone.get_staged_policy("code_review")
        assert staged is not None
        assert staged.policy_id == "security_scan"
        assert staged.confidence == 0.5

    def test_stage_policy_replaces_existing(self, staging_zone):
        """Test that staging replaces existing staged policy for same intent."""
        staging_zone.stage_policy(
            intent="code_review",
            policy_id="security_scan",
            confidence=0.4
        )
        staging_zone.stage_policy(
            intent="code_review",
            policy_id="style_check",
            confidence=0.5
        )

        staged = staging_zone.get_staged_policy("code_review")
        assert staged.policy_id == "style_check"
        assert staged.confidence == 0.5

    def test_stage_policy_with_metadata(self, staging_zone):
        """Test staging with metadata."""
        staging_zone.stage_policy(
            intent="code_review",
            policy_id="security_scan",
            confidence=0.5,
            metadata={"source": "intent_router", "priority": "high"}
        )

        staged = staging_zone.get_staged_policy("code_review")
        assert staged.metadata["source"] == "intent_router"
        assert staged.metadata["priority"] == "high"

    def test_stage_policy_max_staged_limit(self, configured_staging_zone):
        """Test that max_staged limit is enforced."""
        for i in range(10):
            configured_staging_zone.stage_policy(
                intent=f"intent_{i}",
                policy_id=f"policy_{i}",
                confidence=0.5
            )

        # Should fail when limit is reached
        with pytest.raises(ValueError, match="Maximum staged policies"):
            configured_staging_zone.stage_policy(
                intent="intent_11",
                policy_id="policy_11",
                confidence=0.5
            )

    def test_stage_policy_emits_event(self, staging_zone_with_deps):
        """Test that staging emits POLICY_STAGED event."""
        staging_zone_with_deps.stage_policy(
            intent="code_review",
            policy_id="security_scan",
            confidence=0.5
        )

        # Verify event was emitted
        event_bus = staging_zone_with_deps._event_bus
        assert event_bus.emit.called
        call_args = event_bus.emit.call_args
        event = call_args[0][0]
        assert event.event_type == "POLICY_STAGED"
        assert event.data["intent"] == "code_review"


# =============================================================================
# Test PolicyStagingZone.get_staged_policy()
# =============================================================================

class TestGetStagedPolicy:
    """Tests for PolicyStagingZone.get_staged_policy() method."""

    def test_get_staged_policy_exists(self, staging_zone):
        """Test getting a staged policy that exists."""
        staging_zone.stage_policy(
            intent="code_review",
            policy_id="security_scan",
            confidence=0.5
        )

        staged = staging_zone.get_staged_policy("code_review")
        assert staged is not None
        assert staged.policy_id == "security_scan"

    def test_get_staged_policy_not_exists(self, staging_zone):
        """Test getting a staged policy that doesn't exist."""
        staged = staging_zone.get_staged_policy("nonexistent")
        assert staged is None

    def test_get_staged_policy_expired(self, staging_zone):
        """Test that expired policies return None."""
        # Stage a policy that's already expired
        staging_zone._staged["expired_intent"] = StagedPolicy(
            intent="expired_intent",
            policy_id="test_policy",
            confidence=0.5,
            expires_at=datetime.utcnow() - timedelta(seconds=1)
        )

        staged = staging_zone.get_staged_policy("expired_intent")
        assert staged is None


# =============================================================================
# Test PolicyStagingZone.commit_policy()
# =============================================================================

class TestCommitPolicy:
    """Tests for PolicyStagingZone.commit_policy() method."""

    def test_commit_policy_success(self, staging_zone):
        """Test successful policy commitment with sufficient confidence."""
        staging_zone.stage_policy(
            intent="code_review",
            policy_id="security_scan",
            confidence=0.7  # Above min_confidence of 0.6
        )

        policy_id = staging_zone.commit_policy("code_review")
        assert policy_id == "security_scan"

        # Should be removed after commit
        staged = staging_zone.get_staged_policy("code_review")
        assert staged is None

    def test_commit_policy_no_staged(self, staging_zone):
        """Test commit with no staged policy."""
        with pytest.raises(NoStagedPolicyError):
            staging_zone.commit_policy("nonexistent")

    def test_commit_policy_insufficient_clarity(self, staging_zone):
        """Test commit with insufficient clarity."""
        staging_zone.stage_policy(
            intent="code_review",
            policy_id="security_scan",
            confidence=0.4  # Below min_confidence of 0.6
        )

        with pytest.raises(InsufficientClarityError) as exc_info:
            staging_zone.commit_policy("code_review")

        assert exc_info.value.confidence == 0.4
        assert exc_info.value.min_confidence == 0.6

    def test_commit_policy_expired(self, staging_zone):
        """Test commit with expired policy."""
        staging_zone.stage_policy(
            intent="code_review",
            policy_id="security_scan",
            confidence=0.7
        )

        # Manually expire the policy
        staging_zone._staged["code_review"].expires_at = datetime.utcnow() - timedelta(seconds=1)

        with pytest.raises(StagedPolicyExpiredError):
            staging_zone.commit_policy("code_review")

    def test_commit_policy_with_policy_engine(self, staging_zone_with_deps):
        """Test that commit calls policy engine activate."""
        staging_zone_with_deps.stage_policy(
            intent="code_review",
            policy_id="security_scan",
            confidence=0.7
        )

        staging_zone_with_deps.commit_policy("code_review")

        # Verify policy engine was called
        staging_zone_with_deps._policy_engine.activate.assert_called_once_with("security_scan")

    def test_commit_policy_emits_event(self, staging_zone_with_deps):
        """Test that commit emits POLICY_COMMITTED event."""
        staging_zone_with_deps.stage_policy(
            intent="code_review",
            policy_id="security_scan",
            confidence=0.7
        )

        staging_zone_with_deps.commit_policy("code_review")

        # Find the POLICY_COMMITTED event
        event_bus = staging_zone_with_deps._event_bus
        calls = event_bus.emit.call_args_list
        commit_event = None
        for call in calls:
            event = call[0][0]
            if event.event_type == "POLICY_COMMITTED":
                commit_event = event
                break

        assert commit_event is not None
        assert commit_event.data["intent"] == "code_review"
        # The policy_id in the event is the activated_id from policy engine
        # Since we have a mock that returns "activated_policy_id"
        assert commit_event.data["policy_id"] == "activated_policy_id"


# =============================================================================
# Test PolicyStagingZone.rollback()
# =============================================================================

class TestRollback:
    """Tests for PolicyStagingZone.rollback() method."""

    def test_rollback_success(self, staging_zone):
        """Test successful rollback."""
        staging_zone.stage_policy(
            intent="code_review",
            policy_id="security_scan",
            confidence=0.5
        )

        staging_zone.rollback("code_review")

        # Should be removed
        staged = staging_zone.get_staged_policy("code_review")
        assert staged is None

    def test_rollback_nonexistent_silent(self, staging_zone):
        """Test that rollback of nonexistent policy is silent."""
        # Should not raise
        staging_zone.rollback("nonexistent")

    def test_rollback_emits_event(self, staging_zone_with_deps):
        """Test that rollback emits POLICY_ROLLBACK event."""
        staging_zone_with_deps.stage_policy(
            intent="code_review",
            policy_id="security_scan",
            confidence=0.5
        )

        staging_zone_with_deps.rollback("code_review")

        # Find the POLICY_ROLLBACK event
        event_bus = staging_zone_with_deps._event_bus
        calls = event_bus.emit.call_args_list
        rollback_event = None
        for call in calls:
            event = call[0][0]
            if event.event_type == "POLICY_ROLLBACK":
                rollback_event = event
                break

        assert rollback_event is not None
        assert rollback_event.data["intent"] == "code_review"


# =============================================================================
# Test PolicyStagingZone.get_all_staged()
# =============================================================================

class TestGetAllStaged:
    """Tests for PolicyStagingZone.get_all_staged() method."""

    def test_get_all_staged_empty(self, staging_zone):
        """Test getting all staged when empty."""
        staged = staging_zone.get_all_staged()
        assert staged == []

    def test_get_all_staged_multiple(self, staging_zone):
        """Test getting all staged policies."""
        staging_zone.stage_policy("intent_1", "policy_1", 0.5)
        staging_zone.stage_policy("intent_2", "policy_2", 0.6)
        staging_zone.stage_policy("intent_3", "policy_3", 0.7)

        staged = staging_zone.get_all_staged()
        assert len(staged) == 3

    def test_get_all_staged_excludes_expired(self, staging_zone):
        """Test that get_all_staged excludes expired policies."""
        staging_zone.stage_policy("intent_1", "policy_1", 0.5)
        staging_zone.stage_policy("intent_2", "policy_2", 0.6)

        # Manually expire one
        staging_zone._staged["intent_1"].expires_at = datetime.utcnow() - timedelta(seconds=1)

        staged = staging_zone.get_all_staged()
        assert len(staged) == 1
        assert staged[0].intent == "intent_2"


# =============================================================================
# Test PolicyStagingZone.cleanup_expired()
# =============================================================================

class TestCleanupExpired:
    """Tests for PolicyStagingZone.cleanup_expired() method."""

    def test_cleanup_expired_removes_expired(self, staging_zone):
        """Test that cleanup removes expired policies."""
        staging_zone.stage_policy("intent_1", "policy_1", 0.5)
        staging_zone.stage_policy("intent_2", "policy_2", 0.6)

        # Manually expire one
        staging_zone._staged["intent_1"].expires_at = datetime.utcnow() - timedelta(seconds=1)

        count = staging_zone.cleanup_expired()
        assert count == 1
        assert len(staging_zone.get_all_staged()) == 1

    def test_cleanup_expired_none_expired(self, staging_zone):
        """Test cleanup when no policies are expired."""
        staging_zone.stage_policy("intent_1", "policy_1", 0.5)
        staging_zone.stage_policy("intent_2", "policy_2", 0.6)

        count = staging_zone.cleanup_expired()
        assert count == 0
        assert len(staging_zone.get_all_staged()) == 2


# =============================================================================
# Test PolicyStagingZone.update_confidence()
# =============================================================================

class TestUpdateConfidence:
    """Tests for PolicyStagingZone.update_confidence() method."""

    def test_update_confidence_success(self, staging_zone):
        """Test successful confidence update."""
        staging_zone.stage_policy("code_review", "security_scan", 0.4)

        result = staging_zone.update_confidence("code_review", 0.7)
        assert result is True

        staged = staging_zone.get_staged_policy("code_review")
        assert staged.confidence == 0.7

    def test_update_confidence_nonexistent(self, staging_zone):
        """Test update on nonexistent policy."""
        result = staging_zone.update_confidence("nonexistent", 0.7)
        assert result is False

    def test_update_confidence_expired(self, staging_zone):
        """Test update on expired policy."""
        staging_zone.stage_policy("code_review", "security_scan", 0.4)

        # Manually expire
        staging_zone._staged["code_review"].expires_at = datetime.utcnow() - timedelta(seconds=1)

        result = staging_zone.update_confidence("code_review", 0.7)
        assert result is False

    def test_update_confidence_clamps(self, staging_zone):
        """Test that confidence is clamped on update."""
        staging_zone.stage_policy("code_review", "security_scan", 0.4)

        staging_zone.update_confidence("code_review", 1.5)
        staged = staging_zone.get_staged_policy("code_review")
        assert staged.confidence == 1.0


# =============================================================================
# Test PolicyStagingZone Stats
# =============================================================================

class TestStats:
    """Tests for PolicyStagingZone statistics."""

    def test_get_stats(self, staging_zone):
        """Test getting statistics."""
        staging_zone.stage_policy("intent_1", "policy_1", 0.5)
        staging_zone.stage_policy("intent_2", "policy_2", 0.6)

        stats = staging_zone.get_stats()
        assert stats["current_staged_count"] == 2
        assert stats["total_staged"] == 2
        assert stats["total_committed"] == 0
        assert stats["total_rolled_back"] == 0

    def test_stats_after_commit(self, staging_zone):
        """Test statistics after commit."""
        staging_zone.stage_policy("intent_1", "policy_1", 0.7)
        staging_zone.commit_policy("intent_1")

        stats = staging_zone.get_stats()
        assert stats["total_staged"] == 1
        assert stats["total_committed"] == 1

    def test_stats_after_rollback(self, staging_zone):
        """Test statistics after rollback."""
        staging_zone.stage_policy("intent_1", "policy_1", 0.5)
        staging_zone.rollback("intent_1")

        stats = staging_zone.get_stats()
        assert stats["total_staged"] == 1
        assert stats["total_rolled_back"] == 1


# =============================================================================
# Test Factory Functions
# =============================================================================

class TestFactoryFunctions:
    """Tests for factory functions."""

    def test_create_staging_zone(self):
        """Test create_staging_zone factory function."""
        zone = create_staging_zone()
        assert isinstance(zone, PolicyStagingZone)

    def test_create_staging_zone_with_config(self):
        """Test create_staging_zone with config."""
        zone = create_staging_zone(config={
            "min_confidence": 0.8,
            "max_staged": 50
        })
        assert zone.min_confidence == 0.8
        assert zone.max_staged == 50

    def test_get_staging_zone_singleton(self):
        """Test get_staging_zone returns singleton."""
        reset_staging_zone()

        zone1 = get_staging_zone()
        zone2 = get_staging_zone()
        assert zone1 is zone2

        reset_staging_zone()

    def test_reset_staging_zone(self):
        """Test reset_staging_zone clears singleton."""
        zone1 = get_staging_zone()
        reset_staging_zone()
        zone2 = get_staging_zone()
        assert zone1 is not zone2


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests for PolicyStagingZone."""

    def test_full_workflow_stage_commit(self, staging_zone):
        """Test full workflow: stage with low confidence, update, commit."""
        # Stage with low confidence
        staging_zone.stage_policy("code_review", "security_scan", 0.4)

        # Try to commit - should fail
        with pytest.raises(InsufficientClarityError):
            staging_zone.commit_policy("code_review")

        # Update confidence
        staging_zone.update_confidence("code_review", 0.7)

        # Commit should succeed
        policy_id = staging_zone.commit_policy("code_review")
        assert policy_id == "security_scan"

    def test_full_workflow_stage_rollback(self, staging_zone):
        """Test full workflow: stage, then rollback."""
        staging_zone.stage_policy("code_review", "security_scan", 0.4)

        # Rollback
        staging_zone.rollback("code_review")

        # Verify removed
        assert staging_zone.get_staged_policy("code_review") is None

        # Commit should fail
        with pytest.raises(NoStagedPolicyError):
            staging_zone.commit_policy("code_review")

    def test_policy_staged_when_confidence_below_threshold(self, staging_zone):
        """Validation: Policy staged when confidence < 0.6."""
        # Stage with confidence below threshold
        staging_zone.stage_policy("code_review", "security_scan", 0.4)

        # Should be staged
        staged = staging_zone.get_staged_policy("code_review")
        assert staged is not None
        assert staged.confidence < 0.6

    def test_policy_committed_when_confidence_above_threshold(self, staging_zone):
        """Validation: Policy committed when confidence >= 0.6."""
        # Stage with confidence above threshold
        staging_zone.stage_policy("code_review", "security_scan", 0.7)

        # Should be commitable
        policy_id = staging_zone.commit_policy("code_review")
        assert policy_id == "security_scan"

    def test_staged_policy_can_be_rolled_back(self, staging_zone):
        """Validation: Staged policy can be rolled back."""
        staging_zone.stage_policy("code_review", "security_scan", 0.5)

        staging_zone.rollback("code_review")

        assert staging_zone.get_staged_policy("code_review") is None

    def test_expired_staged_policies_are_cleaned_up(self, staging_zone):
        """Validation: Expired staged policies are cleaned up."""
        staging_zone.stage_policy("intent_1", "policy_1", 0.5)
        staging_zone.stage_policy("intent_2", "policy_2", 0.6)

        # Manually expire one
        staging_zone._staged["intent_1"].expires_at = datetime.utcnow() - timedelta(seconds=1)

        count = staging_zone.cleanup_expired()
        assert count == 1
        assert len(staging_zone.get_all_staged()) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
