"""
Tests for ITEM-FEEDBACK-02: Self-Evolution Engine

This module tests the Self-Evolution Engine implementation for pattern
analysis and skill generation from successful sessions.

Author: TITAN Protocol Team
Version: 1.0.0
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch

from src.evolution.self_evolution import (
    SelfEvolutionEngine,
    SkillDraft,
    EvolutionStats,
    ValidationResult,
)
from src.evolution.pattern_extractor import (
    Pattern,
    PatternExtractor,
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
def mock_skill_library():
    """Create a mock skill library for testing."""
    library = MagicMock()
    library.get_skill = MagicMock(return_value=None)
    library.register_skill = MagicMock(return_value="skill-registered")
    return library


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
def mock_feedback_store():
    """Create a mock feedback store for testing."""
    store = MagicMock()
    store.aggregate_feedback = MagicMock()
    return store


@pytest.fixture
def pattern_extractor(mock_feedback_store, mock_storage):
    """Create a PatternExtractor instance for testing."""
    return PatternExtractor(
        config={},
        feedback_store=mock_feedback_store,
        session_store=mock_storage
    )


@pytest.fixture
def evolution_engine(pattern_extractor, mock_skill_library, mock_event_bus):
    """Create a SelfEvolutionEngine instance for testing."""
    return SelfEvolutionEngine(
        config={"auto_propose_skills": False},
        pattern_extractor=pattern_extractor,
        skill_library=mock_skill_library,
        event_bus=mock_event_bus
    )


# =============================================================================
# Test Pattern
# =============================================================================

class TestPattern:
    """Tests for Pattern dataclass."""

    def test_create_pattern(self):
        """Test creating a Pattern instance."""
        pattern = Pattern(
            pattern_name="test_pattern",
            description="A test pattern",
            session_ids=["sess-001", "sess-002"],
            success_rate=0.95,
            reusability_score=0.8,
            components=["tool1", "tool2"]
        )
        assert pattern.pattern_name == "test_pattern"
        assert len(pattern.session_ids) == 2
        assert pattern.success_rate == 0.95

    def test_pattern_auto_id(self):
        """Test that pattern ID is auto-generated."""
        pattern = Pattern(pattern_name="auto_id_test")
        assert pattern.pattern_id.startswith("pat-")

    def test_pattern_success_rate_bounds(self):
        """Test that success_rate must be within bounds."""
        # Valid bounds
        pattern = Pattern(success_rate=0.5)
        assert pattern.success_rate == 0.5
        
        # Invalid high
        with pytest.raises(ValueError):
            Pattern(success_rate=1.5)
        
        # Invalid low
        with pytest.raises(ValueError):
            Pattern(success_rate=-0.1)

    def test_pattern_reusability_bounds(self):
        """Test that reusability_score must be within bounds."""
        # Invalid high
        with pytest.raises(ValueError):
            Pattern(reusability_score=1.5)

    def test_to_dict(self):
        """Test Pattern serialization."""
        pattern = Pattern(
            pattern_id="pat-test",
            pattern_name="serialization_test",
            session_ids=["s1"],
            success_rate=0.9
        )
        d = pattern.to_dict()
        assert d["pattern_id"] == "pat-test"
        assert d["pattern_name"] == "serialization_test"

    def test_from_dict(self):
        """Test Pattern deserialization."""
        d = {
            "pattern_id": "pat-restore",
            "pattern_name": "restored_pattern",
            "description": "Restored from storage",
            "session_ids": ["s1", "s2"],
            "success_rate": 0.85,
            "reusability_score": 0.7,
            "components": ["comp1"],
            "context_requirements": {"type": "test"},
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z"
        }
        pattern = Pattern.from_dict(d)
        assert pattern.pattern_id == "pat-restore"
        assert pattern.success_rate == 0.85

    def test_get_hash(self):
        """Test pattern hash generation."""
        pattern = Pattern(
            pattern_name="hash_test",
            components=["a", "b"]
        )
        hash_val = pattern.get_hash()
        assert len(hash_val) == 16

    def test_merge_with(self):
        """Test merging two patterns."""
        pattern1 = Pattern(
            pattern_name="merged",
            session_ids=["s1", "s2"],
            success_rate=0.9,
            components=["a"]
        )
        pattern2 = Pattern(
            pattern_name="merged",
            session_ids=["s2", "s3"],
            success_rate=0.8,
            components=["b"]
        )
        
        merged = pattern1.merge_with(pattern2)
        
        assert len(merged.session_ids) == 3
        assert "a" in merged.components
        assert "b" in merged.components

    def test_hashable(self):
        """Test that Pattern is hashable."""
        pattern = Pattern(pattern_id="pat-hash", pattern_name="hashable")
        pattern_set = {pattern}
        assert len(pattern_set) == 1

    def test_equality(self):
        """Test Pattern equality."""
        p1 = Pattern(pattern_id="pat-same", pattern_name="a")
        p2 = Pattern(pattern_id="pat-same", pattern_name="b")
        p3 = Pattern(pattern_id="pat-different", pattern_name="a")
        
        assert p1 == p2
        assert p1 != p3


# =============================================================================
# Test PatternExtractor
# =============================================================================

class TestPatternExtractor:
    """Tests for PatternExtractor class."""

    def test_extract_from_session_no_data(
        self, pattern_extractor, mock_storage
    ):
        """Test extraction when session data doesn't exist."""
        mock_storage.load_json.side_effect = Exception("Not found")
        
        patterns = pattern_extractor.extract_from_session("nonexistent")
        
        assert patterns == []

    def test_extract_from_session_low_success_rate(
        self, pattern_extractor, mock_storage
    ):
        """Test extraction skips low success rate sessions."""
        mock_storage.load_json.return_value = {
            "success_rate": 0.5,  # Below default threshold of 0.8
            "tool_history": []
        }
        
        patterns = pattern_extractor.extract_from_session("sess-low")
        
        assert patterns == []

    def test_calculate_pattern_reusability(self, pattern_extractor):
        """Test pattern reusability calculation."""
        pattern = Pattern(
            session_ids=["s1", "s2", "s3"],
            success_rate=0.9,
            components=["tool1", "tool2"]
        )
        
        reusability = pattern_extractor.calculate_pattern_reusability(pattern)
        
        assert 0.0 <= reusability <= 1.0
        assert reusability > 0  # Should have some reusability

    def test_calculate_pattern_reusability_no_sessions(self, pattern_extractor):
        """Test reusability calculation with no sessions."""
        pattern = Pattern(session_ids=[])
        
        reusability = pattern_extractor.calculate_pattern_reusability(pattern)
        
        assert reusability == 0.0

    def test_find_common_patterns_empty(self, pattern_extractor):
        """Test finding common patterns with empty session list."""
        patterns = pattern_extractor.find_common_patterns([])
        assert patterns == []

    def test_cluster_patterns(self, pattern_extractor):
        """Test pattern clustering."""
        patterns = [
            Pattern(pattern_name="cluster", components=["a", "b"]),
            Pattern(pattern_name="cluster", components=["a", "b", "c"]),
            Pattern(pattern_name="different", components=["x", "y", "z"]),
        ]
        
        clustered = pattern_extractor._cluster_patterns(patterns)
        
        assert len(clustered) <= len(patterns)

    def test_calculate_similarity(self, pattern_extractor):
        """Test pattern similarity calculation."""
        p1 = Pattern(pattern_name="same", components=["a", "b"])
        p2 = Pattern(pattern_name="same", components=["a", "b"])
        p3 = Pattern(pattern_name="different", components=["x", "y"])
        
        sim_same = pattern_extractor._calculate_similarity(p1, p2)
        sim_diff = pattern_extractor._calculate_similarity(p1, p3)
        
        assert sim_same > sim_diff
        assert 0.0 <= sim_same <= 1.0


# =============================================================================
# Test SkillDraft
# =============================================================================

class TestSkillDraft:
    """Tests for SkillDraft dataclass."""

    def test_create_skill_draft(self):
        """Test creating a SkillDraft instance."""
        draft = SkillDraft(
            pattern_source="pat-abc123",
            proposed_skill_id="auto_ast_chunking",
            description="Automatically chunk code using AST analysis",
            applicable_to=["AUDIT_CODE", "REVIEW_CODE"],
            confidence=0.85
        )
        assert draft.proposed_skill_id == "auto_ast_chunking"
        assert draft.confidence == 0.85
        assert draft.status == "DRAFT"

    def test_skill_draft_auto_id(self):
        """Test that draft ID is auto-generated."""
        draft = SkillDraft()
        assert draft.draft_id.startswith("draft-")

    def test_skill_draft_confidence_bounds(self):
        """Test that confidence must be within bounds."""
        # Valid
        draft = SkillDraft(confidence=0.5)
        assert draft.confidence == 0.5
        
        # Invalid high
        with pytest.raises(ValueError):
            SkillDraft(confidence=1.5)
        
        # Invalid low
        with pytest.raises(ValueError):
            SkillDraft(confidence=-0.1)

    def test_skill_draft_invalid_status(self):
        """Test that invalid status raises ValueError."""
        with pytest.raises(ValueError):
            SkillDraft(status="INVALID_STATUS")

    def test_to_dict(self):
        """Test SkillDraft serialization."""
        draft = SkillDraft(
            draft_id="draft-test",
            proposed_skill_id="test_skill",
            description="Test description",
            applicable_to=["TASK_A"],
            confidence=0.75
        )
        d = draft.to_dict()
        assert d["draft_id"] == "draft-test"
        assert d["proposed_skill_id"] == "test_skill"

    def test_from_dict(self):
        """Test SkillDraft deserialization."""
        d = {
            "draft_id": "draft-restore",
            "pattern_source": "pat-source",
            "proposed_skill_id": "restored_skill",
            "description": "Restored skill",
            "applicable_to": ["TASK_X"],
            "required_tools": ["tool1"],
            "role_hints": ["developer"],
            "validation_chain": ["check1"],
            "confidence": 0.8,
            "status": "PROPOSED",
            "created_at": "2024-01-01T00:00:00Z"
        }
        draft = SkillDraft.from_dict(d)
        assert draft.draft_id == "draft-restore"
        assert draft.status == "PROPOSED"

    def test_is_ready_for_proposal(self):
        """Test is_ready_for_proposal method."""
        # Not ready - missing fields
        draft1 = SkillDraft(confidence=0.8)
        assert draft1.is_ready_for_proposal() is False
        
        # Ready - all required fields
        draft2 = SkillDraft(
            proposed_skill_id="test_skill",
            description="A valid description",
            applicable_to=["TASK_A"],
            confidence=0.75
        )
        assert draft2.is_ready_for_proposal() is True
        
        # Not ready - confidence too low
        draft3 = SkillDraft(
            proposed_skill_id="test_skill",
            description="Description",
            applicable_to=["TASK_A"],
            confidence=0.5
        )
        assert draft3.is_ready_for_proposal() is False


# =============================================================================
# Test EvolutionStats
# =============================================================================

class TestEvolutionStats:
    """Tests for EvolutionStats dataclass."""

    def test_create_evolution_stats(self):
        """Test creating EvolutionStats instance."""
        stats = EvolutionStats(
            patterns_analyzed=100,
            drafts_generated=10,
            drafts_approved=8,
            drafts_rejected=2,
            skills_created=8
        )
        assert stats.patterns_analyzed == 100
        assert stats.skills_created == 8

    def test_approval_rate(self):
        """Test approval rate calculation."""
        stats = EvolutionStats(
            drafts_approved=8,
            drafts_rejected=2
        )
        assert stats.approval_rate() == 0.8

    def test_approval_rate_no_drafts(self):
        """Test approval rate with no drafts."""
        stats = EvolutionStats()
        assert stats.approval_rate() == 0.0

    def test_to_dict(self):
        """Test EvolutionStats serialization."""
        stats = EvolutionStats(
            patterns_analyzed=50,
            drafts_generated=5
        )
        d = stats.to_dict()
        assert d["patterns_analyzed"] == 50

    def test_from_dict(self):
        """Test EvolutionStats deserialization."""
        d = {
            "patterns_analyzed": 200,
            "drafts_generated": 20,
            "drafts_approved": 15,
            "drafts_rejected": 5,
            "skills_created": 15,
            "last_analysis": "2024-01-01T00:00:00Z"
        }
        stats = EvolutionStats.from_dict(d)
        assert stats.patterns_analyzed == 200


# =============================================================================
# Test ValidationResult
# =============================================================================

class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_create_valid_result(self):
        """Test creating a valid ValidationResult."""
        result = ValidationResult(valid=True)
        assert result.valid is True
        assert result.issues == []

    def test_create_invalid_result(self):
        """Test creating an invalid ValidationResult."""
        result = ValidationResult(
            valid=False,
            issues=["Missing skill_id", "Description too short"],
            suggestions=["Add skill_id", "Expand description"]
        )
        assert result.valid is False
        assert len(result.issues) == 2

    def test_to_dict(self):
        """Test ValidationResult serialization."""
        result = ValidationResult(
            valid=False,
            issues=["Issue 1"],
            suggestions=["Suggestion 1"]
        )
        d = result.to_dict()
        assert d["valid"] is False
        assert d["issues"] == ["Issue 1"]

    def test_from_dict(self):
        """Test ValidationResult deserialization."""
        d = {
            "valid": True,
            "issues": [],
            "suggestions": []
        }
        result = ValidationResult.from_dict(d)
        assert result.valid is True


# =============================================================================
# Test SelfEvolutionEngine.analyze_successful_patterns()
# =============================================================================

class TestSelfEvolutionEngineAnalyzePatterns:
    """Tests for SelfEvolutionEngine.analyze_successful_patterns() method."""

    def test_analyze_successful_patterns_empty(
        self, evolution_engine, mock_storage
    ):
        """Test analysis when no successful sessions exist."""
        mock_storage.list.return_value = []
        
        patterns = evolution_engine.analyze_successful_patterns(
            timedelta(days=7)
        )
        
        assert patterns == []

    def test_analyze_updates_stats(
        self, evolution_engine, mock_storage
    ):
        """Test that analysis updates evolution stats."""
        mock_storage.list.return_value = []
        
        evolution_engine.analyze_successful_patterns(timedelta(days=7))
        
        stats = evolution_engine.get_evolution_stats()
        assert isinstance(stats, EvolutionStats)


# =============================================================================
# Test SelfEvolutionEngine.extract_skill_candidate()
# =============================================================================

class TestSelfEvolutionEngineExtractSkillCandidate:
    """Tests for SelfEvolutionEngine.extract_skill_candidate() method."""

    def test_extract_skill_candidate(self, evolution_engine):
        """Test extracting a skill candidate from a pattern."""
        pattern = Pattern(
            pattern_name="ast_chunking",
            description="Use AST parsing to chunk code",
            session_ids=["s1", "s2", "s3"],
            success_rate=0.95,
            reusability_score=0.85,
            components=["ast_parser", "semantic_analyzer"],
            context_requirements={"task_type": "AUDIT_CODE"}
        )
        
        draft = evolution_engine.extract_skill_candidate(pattern)
        
        assert draft.pattern_source == pattern.pattern_id
        assert draft.proposed_skill_id.startswith("auto_")
        assert draft.confidence > 0
        assert draft.status == "DRAFT"

    def test_extract_emits_event(
        self, evolution_engine, mock_event_bus
    ):
        """Test that extract emits SKILL_DRAFT_CREATED event."""
        pattern = Pattern(
            pattern_name="test_pattern",
            session_ids=["s1"],
            success_rate=0.9,
            reusability_score=0.8
        )
        
        evolution_engine.extract_skill_candidate(pattern)
        
        assert mock_event_bus.emit.called


# =============================================================================
# Test SelfEvolutionEngine.validate_skill_draft()
# =============================================================================

class TestSelfEvolutionEngineValidateSkillDraft:
    """Tests for SelfEvolutionEngine.validate_skill_draft() method."""

    def test_validate_valid_draft(self, evolution_engine):
        """Test validation of a valid skill draft."""
        draft = SkillDraft(
            proposed_skill_id="valid_skill",
            description="A valid skill description that is long enough",
            applicable_to=["AUDIT_CODE"],
            confidence=0.8
        )
        
        result = evolution_engine.validate_skill_draft(draft)
        
        assert result.valid is True
        assert len(result.issues) == 0

    def test_validate_missing_skill_id(self, evolution_engine):
        """Test validation catches missing skill ID."""
        draft = SkillDraft(
            description="Valid description",
            applicable_to=["TASK_A"],
            confidence=0.8
        )
        
        result = evolution_engine.validate_skill_draft(draft)
        
        assert result.valid is False
        assert any("skill_id" in issue.lower() for issue in result.issues)

    def test_validate_missing_description(self, evolution_engine):
        """Test validation catches missing description."""
        draft = SkillDraft(
            proposed_skill_id="test_skill",
            applicable_to=["TASK_A"],
            confidence=0.8
        )
        
        result = evolution_engine.validate_skill_draft(draft)
        
        assert result.valid is False
        assert any("description" in issue.lower() for issue in result.issues)

    def test_validate_short_description(self, evolution_engine):
        """Test validation catches short description."""
        draft = SkillDraft(
            proposed_skill_id="test_skill",
            description="Too short",  # Less than 20 characters
            applicable_to=["TASK_A"],
            confidence=0.8
        )
        
        result = evolution_engine.validate_skill_draft(draft)
        
        assert result.valid is False
        assert any("short" in issue.lower() for issue in result.issues)

    def test_validate_no_task_types(self, evolution_engine):
        """Test validation catches missing task types."""
        draft = SkillDraft(
            proposed_skill_id="test_skill",
            description="A valid description here",
            applicable_to=[],
            confidence=0.8
        )
        
        result = evolution_engine.validate_skill_draft(draft)
        
        assert result.valid is False
        assert any("task" in issue.lower() for issue in result.issues)

    def test_validate_low_confidence(self, evolution_engine):
        """Test validation catches low confidence."""
        draft = SkillDraft(
            proposed_skill_id="test_skill",
            description="Valid description here",
            applicable_to=["TASK_A"],
            confidence=0.5  # Below default min of 0.7
        )
        
        result = evolution_engine.validate_skill_draft(draft)
        
        assert result.valid is False
        assert any("confidence" in issue.lower() for issue in result.issues)

    def test_validate_duplicate_skill(
        self, evolution_engine, mock_skill_library
    ):
        """Test validation catches duplicate skill ID."""
        mock_skill_library.get_skill.return_value = MagicMock()  # Skill exists
        
        draft = SkillDraft(
            proposed_skill_id="existing_skill",
            description="Valid description here",
            applicable_to=["TASK_A"],
            confidence=0.8
        )
        
        result = evolution_engine.validate_skill_draft(draft)
        
        assert result.valid is False
        assert any("exists" in issue.lower() for issue in result.issues)


# =============================================================================
# Test SelfEvolutionEngine.propose_skill()
# =============================================================================

class TestSelfEvolutionEngineProposeSkill:
    """Tests for SelfEvolutionEngine.propose_skill() method."""

    def test_propose_skill(self, evolution_engine, mock_event_bus):
        """Test proposing a skill draft."""
        draft = SkillDraft(
            proposed_skill_id="test_skill",
            description="Valid description for testing",
            applicable_to=["AUDIT_CODE"],
            confidence=0.8
        )
        
        proposal_id = evolution_engine.propose_skill(draft)
        
        assert proposal_id == draft.draft_id
        assert draft.status == "PROPOSED"

    def test_propose_invalid_draft(self, evolution_engine):
        """Test that invalid draft raises ValueError."""
        draft = SkillDraft(confidence=0.5)  # Invalid - missing required fields
        
        with pytest.raises(ValueError):
            evolution_engine.propose_skill(draft)


# =============================================================================
# Test SelfEvolutionEngine Approval Workflow
# =============================================================================

class TestSelfEvolutionEngineApprovalWorkflow:
    """Tests for skill approval and rejection workflow."""

    def test_get_pending_proposals(
        self, evolution_engine
    ):
        """Test getting pending proposals."""
        proposals = evolution_engine.get_pending_proposals()
        assert isinstance(proposals, list)

    def test_approve_proposal(
        self, evolution_engine, mock_skill_library, mock_event_bus
    ):
        """Test approving a proposal."""
        # First create and propose a draft
        draft = SkillDraft(
            proposed_skill_id="approved_skill",
            description="Valid description for approval",
            applicable_to=["AUDIT_CODE"],
            confidence=0.8
        )
        evolution_engine.propose_skill(draft)
        
        # Approve it
        result = evolution_engine.approve_proposal(draft.draft_id)
        
        assert result is True
        assert mock_skill_library.register_skill.called

    def test_approve_nonexistent_proposal(self, evolution_engine):
        """Test approving a nonexistent proposal."""
        result = evolution_engine.approve_proposal("nonexistent-id")
        assert result is False

    def test_reject_proposal(self, evolution_engine, mock_event_bus):
        """Test rejecting a proposal."""
        # First create and propose a draft with a valid long description
        draft = SkillDraft(
            proposed_skill_id="rejected_skill",
            description="A comprehensive skill description that meets validation requirements for rejection testing purposes",
            applicable_to=["TASK_A"],
            confidence=0.8
        )
        evolution_engine.propose_skill(draft)
        
        # Reject it
        result = evolution_engine.reject_proposal(draft.draft_id, "Not needed")
        
        assert result is True
        assert draft.status == "REJECTED"
        assert draft.rejection_reason == "Not needed"

    def test_reject_nonexistent_proposal(self, evolution_engine):
        """Test rejecting a nonexistent proposal."""
        result = evolution_engine.reject_proposal("nonexistent-id", "Reason")
        assert result is False

    def test_approval_updates_stats(self, evolution_engine, mock_skill_library):
        """Test that approval updates evolution stats."""
        draft = SkillDraft(
            proposed_skill_id="stats_skill",
            description="Description for stats test",
            applicable_to=["TASK_A"],
            confidence=0.8
        )
        evolution_engine.propose_skill(draft)
        
        evolution_engine.approve_proposal(draft.draft_id)
        
        stats = evolution_engine.get_evolution_stats()
        assert stats.drafts_approved >= 1
        assert stats.skills_created >= 1

    def test_rejection_updates_stats(self, evolution_engine):
        """Test that rejection updates evolution stats."""
        draft = SkillDraft(
            proposed_skill_id="rejected_stats",
            description="A detailed description that meets all validation requirements for testing rejection stats tracking",
            applicable_to=["TASK_A"],
            confidence=0.8
        )
        evolution_engine.propose_skill(draft)
        
        evolution_engine.reject_proposal(draft.draft_id, "Test")
        
        stats = evolution_engine.get_evolution_stats()
        assert stats.drafts_rejected >= 1


# =============================================================================
# Integration Tests
# =============================================================================

class TestSelfEvolutionEngineIntegration:
    """Integration tests for SelfEvolutionEngine."""

    def test_full_evolution_workflow(
        self, evolution_engine, mock_skill_library, mock_event_bus
    ):
        """Test complete evolution workflow."""
        # Create a high-quality pattern
        pattern = Pattern(
            pattern_name="integration_test_pattern",
            description="A pattern for integration testing",
            session_ids=["s1", "s2", "s3", "s4", "s5"],
            success_rate=0.95,
            reusability_score=0.9,
            components=["tool_a", "tool_b"],
            context_requirements={"task_type": "INTEGRATION_TEST"}
        )
        
        # Extract skill candidate
        draft = evolution_engine.extract_skill_candidate(pattern)
        
        # Validate
        result = evolution_engine.validate_skill_draft(draft)
        assert result.valid is True
        
        # Propose
        proposal_id = evolution_engine.propose_skill(draft)
        assert proposal_id == draft.draft_id
        
        # Approve
        approve_result = evolution_engine.approve_proposal(draft.draft_id)
        assert approve_result is True
        
        # Verify stats
        stats = evolution_engine.get_evolution_stats()
        assert stats.drafts_approved >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
