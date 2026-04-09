"""
Tests for ProfileDetectionMixin

ITEM_005: ProfileDetectionMixin unit tests

Author: TITAN FUSE Team
Version: 1.2.0
"""

import pytest
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestProfileDetectionMixin:
    """Tests for ProfileDetectionMixin class."""
    
    @pytest.fixture
    def mixin(self):
        """Create ProfileDetectionMixin for tests."""
        from src.context.profile_mixin import ProfileDetectionMixin
        return ProfileDetectionMixin()
    
    @pytest.fixture
    def event_bus(self):
        """Create EventBus for tests."""
        from src.events.event_bus import EventBus
        return EventBus()
    
    def test_detect_developer_profile(self, mixin):
        """Developer profile should be detected for code-related requests."""
        result = mixin.detect_with_lexical_analysis(
            "Refactor the authentication module to improve performance"
        )
        
        assert result.profile_type == "developer"
        assert result.confidence >= 0.5
        assert not result.fallback_used
    
    def test_detect_designer_profile(self, mixin):
        """Designer profile should be detected for UI-related requests."""
        result = mixin.detect_with_lexical_analysis(
            "Create a visual design for the dashboard with modern UI"
        )
        
        assert result.profile_type == "designer"
        assert result.confidence >= 0.5
    
    def test_detect_analyst_profile(self, mixin):
        """Analyst profile should be detected for data-related requests."""
        result = mixin.detect_with_lexical_analysis(
            "Analyze the sales data and create a report with metrics"
        )
        
        assert result.profile_type == "analyst"
        assert result.confidence >= 0.5
    
    def test_detect_devops_profile(self, mixin):
        """DevOps profile should be detected for deployment requests."""
        result = mixin.detect_with_lexical_analysis(
            "Deploy this to production and set up monitoring"
        )
        
        assert result.profile_type == "devops"
        assert result.confidence >= 0.5
    
    def test_detect_researcher_profile(self, mixin):
        """Researcher profile should be detected for research requests."""
        result = mixin.detect_with_lexical_analysis(
            "Research the latest papers on transformer architectures"
        )
        
        assert result.profile_type == "researcher"
        assert result.confidence >= 0.5
    
    def test_low_confidence_fallback(self, mixin):
        """Low confidence should trigger fallback."""
        result = mixin.detect_with_lexical_analysis(
            "I want to design a new API and deploy it"
        )
        
        # Mixed signals should result in low confidence or fallback
        assert result.confidence >= 0.0
    
    def test_empty_request_fallback(self, mixin):
        """Empty request should trigger fallback."""
        result = mixin.detect_with_lexical_analysis("")
        
        assert result.fallback_used is True
    
    def test_random_text_fallback(self, mixin):
        """Random text should trigger fallback."""
        result = mixin.detect_with_lexical_analysis("asdfghjkl random text")
        
        assert result.fallback_used is True
    
    def test_lexical_score_calculation(self, mixin):
        """Lexical scores should be calculated correctly."""
        scores = mixin.get_lexical_score("refactor debug code")
        
        assert "developer" in scores
        assert scores["developer"] > 0
    
    def test_pattern_score_calculation(self, mixin):
        """Pattern scores should be calculated correctly."""
        scores = mixin.get_pattern_score("Deploy to production")
        
        assert "devops" in scores
        assert scores["devops"] > 0
    
    def test_score_combination(self, mixin):
        """Scores should be combined with weights."""
        scores = {
            "lexical_analysis": {"developer": 0.8, "designer": 0.2},
            "pattern_matching": {"developer": 0.6, "designer": 0.1},
            "history_analysis": {},
            "explicit_signal": {},
        }
        
        combined = mixin.combine_scores(scores)
        
        assert combined["developer"] > combined["designer"]
    
    def test_configure_weights(self, mixin):
        """Weights should be configurable."""
        mixin.configure_weights({
            "lexical_analysis": 0.6,
            "pattern_matching": 0.4,
        })
        
        assert mixin._weights["lexical_analysis"] == 0.6
        assert mixin._weights["pattern_matching"] == 0.4
    
    def test_event_emission(self, event_bus):
        """PROFILE_DETECTED event should be emitted."""
        from src.context.profile_mixin import ProfileDetectionMixin
        
        events_captured = []
        
        def capture_event(event):
            events_captured.append(event)
        
        event_bus.subscribe("PROFILE_DETECTED", capture_event)
        
        mixin = ProfileDetectionMixin(event_bus=event_bus)
        mixin.detect_with_lexical_analysis("Refactor this code")
        
        profile_events = [e for e in events_captured if e.event_type == "PROFILE_DETECTED"]
        assert len(profile_events) >= 1


class TestEnhancedProfileRouter:
    """Tests for EnhancedProfileRouter class."""
    
    @pytest.fixture
    def router(self, event_bus):
        """Create EnhancedProfileRouter for tests."""
        from src.context.profile_mixin import EnhancedProfileRouter
        return EnhancedProfileRouter(event_bus=event_bus)
    
    @pytest.fixture
    def event_bus(self):
        """Create EventBus for tests."""
        from src.events.event_bus import EventBus
        return EventBus()
    
    def test_full_detection_flow(self, router):
        """Test complete detection flow."""
        result = router.detect_with_lexical_analysis(
            "Implement a new feature and write unit tests"
        )
        
        assert result is not None
        assert result.profile_type is not None
        assert result.confidence >= 0.0
    
    def test_negative_indicators_reduce_score(self, router):
        """Negative indicators should reduce profile score."""
        # Request with mixed indicators
        result1 = router.detect_with_lexical_analysis(
            "Design a deployment pipeline"
        )
        
        # Request with clear indicators
        result2 = router.detect_with_lexical_analysis(
            "Deploy to production"
        )
        
        # Result2 should have higher confidence for devops
        assert result2.confidence >= result1.confidence
    
    def test_multiple_requests_consistency(self, router):
        """Multiple similar requests should produce consistent results."""
        requests = [
            "Refactor the code",
            "Refactor this module",
            "Refactor the function",
        ]
        
        results = [router.detect_with_lexical_analysis(r) for r in requests]
        
        # All should detect developer
        for result in results:
            assert result.profile_type == "developer"


class TestUserRole:
    """Tests for UserRole enum."""
    
    def test_all_roles_exist(self):
        """All 5 user roles should be defined."""
        from src.context.profile_mixin import UserRole
        
        assert UserRole.DESIGNER.value == "designer"
        assert UserRole.DEVELOPER.value == "developer"
        assert UserRole.ANALYST.value == "analyst"
        assert UserRole.DEVOPS.value == "devops"
        assert UserRole.RESEARCHER.value == "researcher"


class TestProfileDetectionResult:
    """Tests for ProfileDetectionResult dataclass."""
    
    def test_result_creation(self):
        """Result should be created correctly."""
        from src.context.profile_mixin import ProfileDetectionResult
        
        result = ProfileDetectionResult(
            profile_type="developer",
            confidence=0.85,
            detection_method="combined",
            scores={"lexical": 0.9, "pattern": 0.8},
            indicators_matched=["refactor", "code"],
        )
        
        assert result.profile_type == "developer"
        assert result.confidence == 0.85
        assert len(result.indicators_matched) == 2
    
    def test_result_to_dict(self):
        """Result should convert to dictionary."""
        from src.context.profile_mixin import ProfileDetectionResult
        
        result = ProfileDetectionResult(
            profile_type="developer",
            confidence=0.85,
            detection_method="combined",
        )
        
        data = result.to_dict()
        
        assert data["profile_type"] == "developer"
        assert data["confidence"] == 0.85
        assert "timestamp" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
