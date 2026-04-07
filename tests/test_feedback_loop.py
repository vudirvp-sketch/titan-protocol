"""
Tests for ITEM-FEEDBACK-01: FeedbackLoop Module

This module tests the FeedbackLoop implementation for feedback collection,
aggregation, and threshold adjustment.

Author: TITAN Protocol Team
Version: 1.0.0
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch

from src.feedback.feedback_loop import (
    FeedbackLoop,
    FeedbackEvent,
    FeedbackType,
    AggregatedFeedback,
    ThresholdAdjustment,
    ApplyResult,
)
from src.feedback.threshold_adapter import (
    ThresholdAdapter,
    DryRunResult,
    ValidationResult,
)
from src.feedback.catalog_versioning import (
    CatalogVersionManager,
    CatalogVersion,
    CatalogDiff,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_event_bus():
    """Create a mock event bus for testing."""
    bus = MagicMock()
    bus.emit = MagicMock()
    return bus


@pytest.fixture
def mock_storage():
    """Create a mock storage backend for testing."""
    storage = MagicMock()
    storage.save_json = MagicMock()
    storage.load_json = MagicMock(return_value={})
    storage.list = MagicMock(return_value=[])
    storage.save = MagicMock()
    return storage


@pytest.fixture
def feedback_config():
    """Create a feedback configuration for testing."""
    return {
        "min_samples": 10,
        "default_threshold": 0.7,
        "feedback_retention_days": 90,
        "aggregation_window_days": 30,
    }


@pytest.fixture
def feedback_loop(mock_event_bus, mock_storage, feedback_config):
    """Create a FeedbackLoop instance for testing."""
    return FeedbackLoop(
        config=feedback_config,
        event_bus=mock_event_bus,
        storage_backend=mock_storage
    )


# =============================================================================
# Test FeedbackType Enum
# =============================================================================

class TestFeedbackType:
    """Tests for FeedbackType enum."""

    def test_thumbs_up_exists(self):
        """Test THUMBS_UP type exists."""
        assert hasattr(FeedbackType, "THUMBS_UP")
        assert FeedbackType.THUMBS_UP.value == "thumbs_up"

    def test_thumbs_down_exists(self):
        """Test THUMBS_DOWN type exists."""
        assert hasattr(FeedbackType, "THUMBS_DOWN")
        assert FeedbackType.THUMBS_DOWN.value == "thumbs_down"

    def test_rating_exists(self):
        """Test RATING type exists."""
        assert hasattr(FeedbackType, "RATING")
        assert FeedbackType.RATING.value == "rating"

    def test_comment_exists(self):
        """Test COMMENT type exists."""
        assert hasattr(FeedbackType, "COMMENT")
        assert FeedbackType.COMMENT.value == "comment"

    def test_all_types_are_strings(self):
        """Test all feedback type values are strings."""
        for feedback_type in FeedbackType:
            assert isinstance(feedback_type.value, str)


# =============================================================================
# Test FeedbackEvent
# =============================================================================

class TestFeedbackEvent:
    """Tests for FeedbackEvent dataclass."""

    def test_create_feedback_event(self):
        """Test creating a FeedbackEvent instance."""
        event = FeedbackEvent(
            feedback_id="fb-123",
            session_id="sess-abc",
            skill_id="skill-web-search",
            feedback_type=FeedbackType.THUMBS_UP,
            context={"query": "test query"}
        )
        assert event.feedback_id == "fb-123"
        assert event.skill_id == "skill-web-search"
        assert event.feedback_type == FeedbackType.THUMBS_UP

    def test_feedback_event_with_rating(self):
        """Test creating a feedback event with rating."""
        event = FeedbackEvent(
            feedback_id="fb-456",
            session_id="sess-xyz",
            skill_id="skill-code-review",
            feedback_type=FeedbackType.RATING,
            rating=4
        )
        assert event.rating == 4
        assert event.feedback_type == FeedbackType.RATING

    def test_feedback_event_invalid_rating(self):
        """Test that invalid rating raises ValueError."""
        with pytest.raises(ValueError):
            FeedbackEvent(
                feedback_id="fb-789",
                session_id="sess-test",
                skill_id="skill-test",
                feedback_type=FeedbackType.RATING,
                rating=6  # Invalid - should be 1-5
            )

    def test_feedback_event_rating_below_range(self):
        """Test that rating below 1 raises ValueError."""
        with pytest.raises(ValueError):
            FeedbackEvent(
                feedback_id="fb-000",
                session_id="sess-test",
                skill_id="skill-test",
                feedback_type=FeedbackType.RATING,
                rating=0  # Invalid - should be 1-5
            )

    def test_to_dict(self):
        """Test FeedbackEvent serialization."""
        event = FeedbackEvent(
            feedback_id="fb-123",
            session_id="sess-abc",
            skill_id="skill-test",
            feedback_type=FeedbackType.THUMBS_DOWN,
            context={"key": "value"}
        )
        d = event.to_dict()
        assert d["feedback_id"] == "fb-123"
        assert d["feedback_type"] == "thumbs_down"
        assert d["context"] == {"key": "value"}

    def test_from_dict(self):
        """Test FeedbackEvent deserialization."""
        d = {
            "feedback_id": "fb-restore",
            "session_id": "sess-restore",
            "skill_id": "skill-restore",
            "feedback_type": "rating",
            "rating": 5,
            "context": {},
            "timestamp": "2024-01-01T00:00:00Z"
        }
        event = FeedbackEvent.from_dict(d)
        assert event.feedback_id == "fb-restore"
        assert event.feedback_type == FeedbackType.RATING
        assert event.rating == 5

    def test_from_dict_with_string_feedback_type(self):
        """Test deserialization with string feedback type."""
        d = {
            "feedback_id": "fb-test",
            "session_id": "sess-test",
            "skill_id": "skill-test",
            "feedback_type": "thumbs_up"
        }
        event = FeedbackEvent.from_dict(d)
        assert event.feedback_type == FeedbackType.THUMBS_UP


# =============================================================================
# Test AggregatedFeedback
# =============================================================================

class TestAggregatedFeedback:
    """Tests for AggregatedFeedback dataclass."""

    def test_create_aggregated_feedback(self):
        """Test creating an AggregatedFeedback instance."""
        agg = AggregatedFeedback(
            skill_id="skill-test",
            thumbs_up_count=10,
            thumbs_down_count=2,
            total_count=12,
            average_rating=4.5
        )
        assert agg.skill_id == "skill-test"
        assert agg.thumbs_up_count == 10
        assert agg.average_rating == 4.5

    def test_positive_rate_calculation(self):
        """Test positive rate property calculation."""
        agg = AggregatedFeedback(
            skill_id="skill-test",
            thumbs_up_count=8,
            thumbs_down_count=2
        )
        assert agg.positive_rate == 0.8  # 8/(8+2)

    def test_positive_rate_no_thumbs(self):
        """Test positive rate when no thumbs feedback."""
        agg = AggregatedFeedback(skill_id="skill-test")
        assert agg.positive_rate == 0.5  # Neutral default

    def test_to_dict(self):
        """Test AggregatedFeedback serialization."""
        agg = AggregatedFeedback(
            skill_id="skill-test",
            thumbs_up_count=5,
            thumbs_down_count=1,
            total_count=6,
            average_rating=4.2
        )
        d = agg.to_dict()
        assert d["skill_id"] == "skill-test"
        assert d["positive_rate"] == 5/6

    def test_from_dict(self):
        """Test AggregatedFeedback deserialization."""
        d = {
            "skill_id": "skill-restore",
            "thumbs_up_count": 15,
            "thumbs_down_count": 5,
            "total_count": 20,
            "average_rating": 3.8
        }
        agg = AggregatedFeedback.from_dict(d)
        assert agg.thumbs_up_count == 15
        assert agg.positive_rate == 0.75


# =============================================================================
# Test ThresholdAdjustment
# =============================================================================

class TestThresholdAdjustment:
    """Tests for ThresholdAdjustment dataclass."""

    def test_create_threshold_adjustment(self):
        """Test creating a ThresholdAdjustment instance."""
        adj = ThresholdAdjustment(
            skill_id="skill-test",
            current_threshold=0.7,
            new_threshold=0.75,
            magnitude=0.05,
            reason="Increased based on positive feedback"
        )
        assert adj.skill_id == "skill-test"
        assert adj.magnitude == 0.05

    def test_adjustment_has_id(self):
        """Test that adjustment has an auto-generated ID."""
        adj = ThresholdAdjustment(
            skill_id="skill-test",
            current_threshold=0.7,
            new_threshold=0.75,
            magnitude=0.05,
            reason="Test"
        )
        assert adj.adjustment_id.startswith("adj-")

    def test_to_dict(self):
        """Test ThresholdAdjustment serialization."""
        adj = ThresholdAdjustment(
            adjustment_id="adj-test",
            skill_id="skill-test",
            current_threshold=0.7,
            new_threshold=0.8,
            magnitude=0.1,
            reason="Test adjustment"
        )
        d = adj.to_dict()
        assert d["adjustment_id"] == "adj-test"
        assert d["new_threshold"] == 0.8

    def test_from_dict(self):
        """Test ThresholdAdjustment deserialization."""
        d = {
            "adjustment_id": "adj-restore",
            "skill_id": "skill-restore",
            "current_threshold": 0.6,
            "new_threshold": 0.65,
            "magnitude": 0.05,
            "reason": "Restored adjustment",
            "timestamp": "2024-01-01T00:00:00Z"
        }
        adj = ThresholdAdjustment.from_dict(d)
        assert adj.adjustment_id == "adj-restore"
        assert adj.new_threshold == 0.65


# =============================================================================
# Test ApplyResult
# =============================================================================

class TestApplyResult:
    """Tests for ApplyResult dataclass."""

    def test_create_success_result(self):
        """Test creating a successful ApplyResult."""
        result = ApplyResult(
            success=True,
            adjustment_id="adj-123",
            version_id="v-456"
        )
        assert result.success is True
        assert result.version_id == "v-456"
        assert result.error_message is None

    def test_create_failure_result(self):
        """Test creating a failed ApplyResult."""
        result = ApplyResult(
            success=False,
            adjustment_id="adj-123",
            error_message="Catalog update failed"
        )
        assert result.success is False
        assert result.error_message == "Catalog update failed"

    def test_to_dict(self):
        """Test ApplyResult serialization."""
        result = ApplyResult(
            success=True,
            adjustment_id="adj-test",
            version_id="v-001"
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["version_id"] == "v-001"


# =============================================================================
# Test FeedbackLoop.receive_feedback()
# =============================================================================

class TestFeedbackLoopReceiveFeedback:
    """Tests for FeedbackLoop.receive_feedback() method."""

    def test_receive_feedback(self, feedback_loop):
        """Test receiving a feedback event."""
        event = FeedbackEvent(
            feedback_id="fb-001",
            session_id="sess-001",
            skill_id="skill-test",
            feedback_type=FeedbackType.THUMBS_UP
        )
        
        result = feedback_loop.receive_feedback(event)
        
        assert result == "fb-001"

    def test_receive_feedback_generates_id(self, feedback_loop):
        """Test that receive_feedback generates ID if missing."""
        event = FeedbackEvent(
            feedback_id="",
            session_id="sess-001",
            skill_id="skill-test",
            feedback_type=FeedbackType.THUMBS_UP
        )
        
        result = feedback_loop.receive_feedback(event)
        
        assert result.startswith("fb-")

    def test_receive_feedback_stores(self, feedback_loop, mock_storage):
        """Test that receive_feedback stores the feedback."""
        event = FeedbackEvent(
            feedback_id="fb-001",
            session_id="sess-001",
            skill_id="skill-test",
            feedback_type=FeedbackType.THUMBS_UP
        )
        
        feedback_loop.receive_feedback(event)
        
        assert mock_storage.save_json.called

    def test_receive_feedback_emits_event(self, feedback_loop, mock_event_bus):
        """Test that receive_feedback emits FEEDBACK_RECEIVED event."""
        event = FeedbackEvent(
            feedback_id="fb-001",
            session_id="sess-001",
            skill_id="skill-test",
            feedback_type=FeedbackType.THUMBS_UP
        )
        
        feedback_loop.receive_feedback(event)
        
        assert mock_event_bus.emit.called

    def test_receive_feedback_missing_skill_id(self, feedback_loop):
        """Test that missing skill_id raises ValueError."""
        event = FeedbackEvent(
            feedback_id="fb-001",
            session_id="sess-001",
            skill_id="",
            feedback_type=FeedbackType.THUMBS_UP
        )
        
        with pytest.raises(ValueError):
            feedback_loop.receive_feedback(event)

    def test_receive_feedback_missing_session_id(self, feedback_loop):
        """Test that missing session_id raises ValueError."""
        event = FeedbackEvent(
            feedback_id="fb-001",
            session_id="",
            skill_id="skill-test",
            feedback_type=FeedbackType.THUMBS_UP
        )
        
        with pytest.raises(ValueError):
            feedback_loop.receive_feedback(event)


# =============================================================================
# Test FeedbackLoop.aggregate_feedback()
# =============================================================================

class TestFeedbackLoopAggregateFeedback:
    """Tests for FeedbackLoop.aggregate_feedback() method."""

    def test_aggregate_feedback(self, feedback_loop):
        """Test aggregating feedback for a skill."""
        # Add some feedback events
        feedback_loop.receive_feedback(FeedbackEvent(
            feedback_id="fb-001",
            session_id="sess-001",
            skill_id="skill-test",
            feedback_type=FeedbackType.THUMBS_UP
        ))
        feedback_loop.receive_feedback(FeedbackEvent(
            feedback_id="fb-002",
            session_id="sess-002",
            skill_id="skill-test",
            feedback_type=FeedbackType.THUMBS_UP
        ))
        feedback_loop.receive_feedback(FeedbackEvent(
            feedback_id="fb-003",
            session_id="sess-003",
            skill_id="skill-test",
            feedback_type=FeedbackType.THUMBS_DOWN
        ))
        
        result = feedback_loop.aggregate_feedback(
            "skill-test",
            timedelta(days=7)
        )
        
        assert result.skill_id == "skill-test"
        assert result.thumbs_up_count == 2
        assert result.thumbs_down_count == 1
        assert result.total_count == 3

    def test_aggregate_feedback_empty(self, feedback_loop):
        """Test aggregating feedback when no events exist."""
        result = feedback_loop.aggregate_feedback(
            "skill-nonexistent",
            timedelta(days=7)
        )
        
        assert result.thumbs_up_count == 0
        assert result.thumbs_down_count == 0
        assert result.total_count == 0

    def test_aggregate_feedback_with_ratings(self, feedback_loop):
        """Test aggregating feedback including ratings."""
        feedback_loop.receive_feedback(FeedbackEvent(
            feedback_id="fb-001",
            session_id="sess-001",
            skill_id="skill-test",
            feedback_type=FeedbackType.RATING,
            rating=5
        ))
        feedback_loop.receive_feedback(FeedbackEvent(
            feedback_id="fb-002",
            session_id="sess-002",
            skill_id="skill-test",
            feedback_type=FeedbackType.RATING,
            rating=3
        ))
        
        result = feedback_loop.aggregate_feedback(
            "skill-test",
            timedelta(days=7)
        )
        
        assert result.average_rating == 4.0  # (5+3)/2


# =============================================================================
# Test ThresholdAdapter
# =============================================================================

class TestThresholdAdapter:
    """Tests for ThresholdAdapter class."""

    @pytest.fixture
    def adapter_config(self):
        """Create adapter configuration."""
        return {
            "threshold_adapter": {
                "alpha": 0.1,
                "target_rate": 0.8,
                "min_samples": 10,
                "max_adjustment": 0.1,
                "min_threshold": 0.3,
                "max_threshold": 0.95
            }
        }

    @pytest.fixture
    def mock_catalog(self):
        """Create a mock catalog."""
        return {
            "skills": {
                "skill-test": {"threshold": 0.7}
            }
        }

    @pytest.fixture
    def adapter(self, adapter_config, mock_catalog, feedback_loop):
        """Create a ThresholdAdapter instance."""
        return ThresholdAdapter(
            config=adapter_config,
            catalog=mock_catalog,
            feedback_store=feedback_loop
        )

    def test_calculate_new_threshold_high_positive(self, adapter):
        """Test threshold calculation with high positive rate."""
        agg = AggregatedFeedback(
            skill_id="skill-test",
            thumbs_up_count=90,
            thumbs_down_count=10,
            total_count=100
        )
        
        new_threshold = adapter.calculate_new_threshold("skill-test", agg)
        
        # High positive rate should increase threshold
        assert new_threshold > 0.7  # Original threshold

    def test_calculate_new_threshold_low_positive(self, adapter):
        """Test threshold calculation with low positive rate."""
        agg = AggregatedFeedback(
            skill_id="skill-test",
            thumbs_up_count=40,
            thumbs_down_count=60,
            total_count=100
        )
        
        new_threshold = adapter.calculate_new_threshold("skill-test", agg)
        
        # Low positive rate should decrease threshold
        assert new_threshold < 0.7  # Original threshold

    def test_validate_threshold_valid(self, adapter):
        """Test threshold validation with valid threshold."""
        result = adapter.validate_threshold(0.7, "skill-test")
        assert result == ValidationResult.VALID

    def test_validate_threshold_too_low(self, adapter):
        """Test threshold validation with too low threshold."""
        result = adapter.validate_threshold(0.2, "skill-test")
        assert result == ValidationResult.TOO_LOW

    def test_validate_threshold_too_high(self, adapter):
        """Test threshold validation with too high threshold."""
        result = adapter.validate_threshold(0.99, "skill-test")
        assert result == ValidationResult.TOO_HIGH

    def test_dry_run_adjustment(self, adapter):
        """Test dry run adjustment simulation."""
        result = adapter.dry_run_adjustment("skill-test", 0.8)
        
        assert result.skill_id == "skill-test"
        assert result.current_threshold == 0.7
        assert result.proposed_threshold == 0.8
        assert isinstance(result.safe, bool)
        assert isinstance(result.warnings, list)

    def test_dry_run_adjustment_to_dict(self, adapter):
        """Test dry run result serialization."""
        result = adapter.dry_run_adjustment("skill-test", 0.8)
        d = result.to_dict()
        
        assert "skill_id" in d
        assert "current_threshold" in d
        assert "proposed_threshold" in d


# =============================================================================
# Test CatalogVersionManager
# =============================================================================

class TestCatalogVersionManager:
    """Tests for CatalogVersionManager class."""

    @pytest.fixture
    def version_manager(self, mock_storage):
        """Create a CatalogVersionManager instance."""
        return CatalogVersionManager(mock_storage)

    def test_create_version(self, version_manager, mock_storage):
        """Test creating a new catalog version."""
        catalog = {
            "version": "1.0.0",
            "skills": {"skill-test": {"threshold": 0.7}}
        }
        
        version_id = version_manager.create_version(catalog, "Initial version")
        
        assert version_id.startswith("v-")
        assert mock_storage.save_json.called

    def test_list_versions_empty(self, version_manager):
        """Test listing versions when none exist."""
        versions = version_manager.list_versions()
        assert versions == []

    def test_get_version_count(self, version_manager):
        """Test getting version count."""
        count = version_manager.get_version_count()
        assert count >= 0

    def test_get_stats(self, version_manager):
        """Test getting version statistics."""
        stats = version_manager.get_stats()
        
        assert "total_versions" in stats
        assert "versions_path" in stats


# =============================================================================
# Test CatalogVersion
# =============================================================================

class TestCatalogVersion:
    """Tests for CatalogVersion dataclass."""

    def test_create_catalog_version(self):
        """Test creating a CatalogVersion instance."""
        version = CatalogVersion(
            version_id="v-test123",
            catalog={"skills": {}},
            reason="Test version"
        )
        assert version.version_id == "v-test123"
        assert version.reason == "Test version"

    def test_checksum_computed(self):
        """Test that checksum is computed on creation."""
        version = CatalogVersion(
            version_id="v-test",
            catalog={"skills": {"s1": {}}},
            reason="Test"
        )
        assert len(version.checksum) > 0

    def test_verify_integrity(self):
        """Test integrity verification."""
        version = CatalogVersion(
            version_id="v-test",
            catalog={"skills": {"s1": {"threshold": 0.7}}},
            reason="Test"
        )
        assert version.verify_integrity() is True

    def test_verify_integrity_tampered(self):
        """Test integrity verification with tampered data."""
        version = CatalogVersion(
            version_id="v-test",
            catalog={"skills": {"s1": {"threshold": 0.7}}},
            reason="Test"
        )
        # Tamper with catalog
        version.catalog = {"skills": {"s1": {"threshold": 0.5}}}
        assert version.verify_integrity() is False

    def test_to_dict(self):
        """Test CatalogVersion serialization."""
        version = CatalogVersion(
            version_id="v-test",
            catalog={"skills": {}},
            reason="Test version"
        )
        d = version.to_dict()
        assert d["version_id"] == "v-test"
        assert "checksum" in d

    def test_from_dict(self):
        """Test CatalogVersion deserialization."""
        d = {
            "version_id": "v-restore",
            "catalog": {"skills": {"s1": {}}},
            "reason": "Restored version",
            "timestamp": "2024-01-01T00:00:00Z",
            "checksum": "abc123"
        }
        version = CatalogVersion.from_dict(d)
        assert version.version_id == "v-restore"
        assert version.reason == "Restored version"


# =============================================================================
# Test CatalogDiff
# =============================================================================

class TestCatalogDiff:
    """Tests for CatalogDiff dataclass."""

    def test_create_catalog_diff(self):
        """Test creating a CatalogDiff instance."""
        diff = CatalogDiff(
            version_id_from="v-001",
            version_id_to="v-002",
            added_skills=["skill-new"],
            removed_skills=["skill-old"],
            modified_skills={"skill-mod": {"threshold": {"from": 0.7, "to": 0.8}}}
        )
        assert diff.version_id_from == "v-001"
        assert "skill-new" in diff.added_skills

    def test_to_dict(self):
        """Test CatalogDiff serialization."""
        diff = CatalogDiff(
            version_id_from="v-001",
            version_id_to="v-002",
            added_skills=["s1"],
            removed_skills=["s2"]
        )
        d = diff.to_dict()
        assert d["version_id_from"] == "v-001"
        assert "summary" in d


# =============================================================================
# Integration Tests
# =============================================================================

class TestFeedbackLoopIntegration:
    """Integration tests for FeedbackLoop."""

    def test_full_feedback_workflow(
        self, mock_event_bus, mock_storage, feedback_config
    ):
        """Test complete feedback collection and aggregation workflow."""
        feedback_loop = FeedbackLoop(
            config=feedback_config,
            event_bus=mock_event_bus,
            storage_backend=mock_storage
        )
        
        # Collect multiple feedback events
        for i in range(5):
            feedback_loop.receive_feedback(FeedbackEvent(
                feedback_id=f"fb-{i:03d}",
                session_id=f"sess-{i:03d}",
                skill_id="skill-integration",
                feedback_type=FeedbackType.THUMBS_UP
            ))
        
        # Aggregate feedback
        agg = feedback_loop.aggregate_feedback(
            "skill-integration",
            timedelta(days=7)
        )
        
        assert agg.thumbs_up_count == 5
        assert agg.thumbs_down_count == 0

    def test_feedback_stats(
        self, feedback_loop
    ):
        """Test getting feedback statistics."""
        feedback_loop.receive_feedback(FeedbackEvent(
            feedback_id="fb-001",
            session_id="sess-001",
            skill_id="skill-stats",
            feedback_type=FeedbackType.THUMBS_UP
        ))
        
        stats = feedback_loop.get_feedback_stats("skill-stats")
        
        assert stats["skill_id"] == "skill-stats"
        assert stats["thumbs_up"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
