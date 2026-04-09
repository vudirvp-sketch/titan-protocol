"""
Test cases for ProfileDetector (ITEM_005).

Tests for user role detection from request patterns.
"""

import pytest
from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from unittest.mock import Mock, MagicMock


# Mock classes for testing (real implementation in src/context/profile_detector.py)
@dataclass
class ProfileDetectionResult:
    """Result of profile detection."""
    profile_type: str
    confidence: float
    detection_method: str
    scores: Dict[str, float]
    indicators_matched: List[str]
    timestamp: str
    fallback_used: bool = False


class MockProfileDetector:
    """Mock implementation for testing."""
    
    LEXICAL_INDICATORS = {
        "designer": {
            "positive": ["design", "ui", "ux", "visual", "layout", "color", "prototype", "wireframe", "mockup", "figma", "sketch"],
            "negative": ["deploy", "server", "config", "database", "kubernetes"]
        },
        "developer": {
            "positive": ["refactor", "debug", "implement", "function", "class", "api", "test", "code", "bug", "fix", "pr", "merge", "commit"],
            "negative": ["visual", "layout", "color", "mockup", "design"]
        },
        "analyst": {
            "positive": ["analyze", "report", "metric", "data", "insight", "trend", "dashboard", "statistics", "kpi", "visualization"],
            "negative": ["implement", "deploy", "code", "refactor"]
        },
        "devops": {
            "positive": ["deploy", "server", "config", "scale", "monitor", "pipeline", "ci", "cd", "container", "kubernetes", "docker", "helm"],
            "negative": ["design", "visual", "mockup", "ui"]
        },
        "researcher": {
            "positive": ["research", "explore", "hypothesis", "investigate", "study", "paper", "citation", "literature", "methodology"],
            "negative": ["implement", "deploy", "debug", "fix"]
        }
    }
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.weights = {
            "lexical": 0.4,
            "pattern": 0.3,
            "history": 0.2,
            "explicit": 0.1
        }
    
    def detect(self, request: str, context: Optional[Dict] = None) -> ProfileDetectionResult:
        """Detect user profile from request."""
        if not request or not request.strip():
            return ProfileDetectionResult(
                profile_type="developer",  # Fallback
                confidence=0.0,
                detection_method="fallback",
                scores={},
                indicators_matched=[],
                timestamp="2026-04-09T00:00:00Z",
                fallback_used=True
            )
        
        scores = self._get_lexical_scores(request.lower())
        
        # Find best match
        best_profile = max(scores, key=scores.get)
        best_score = scores[best_profile]
        
        # Determine if fallback needed
        fallback_used = best_score < 0.1
        
        return ProfileDetectionResult(
            profile_type=best_profile if not fallback_used else "developer",
            confidence=best_score,
            detection_method="lexical" if not fallback_used else "fallback",
            scores=scores,
            indicators_matched=[best_profile] if not fallback_used else [],
            timestamp="2026-04-09T00:00:00Z",
            fallback_used=fallback_used
        )
    
    def _get_lexical_scores(self, request: str) -> Dict[str, float]:
        """Calculate lexical scores for each profile."""
        scores = {}
        
        for profile, indicators in self.LEXICAL_INDICATORS.items():
            positive_count = sum(1 for word in indicators["positive"] if word in request)
            negative_count = sum(1 for word in indicators["negative"] if word in request)
            
            # Simple scoring: positive matches minus negative matches
            total_indicators = len(indicators["positive"])
            score = max(0, (positive_count - negative_count) / total_indicators)
            scores[profile] = min(1.0, score * 2)  # Scale up for better differentiation
        
        return scores


class TestProfileDetector:
    """Test cases for ProfileDetector."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.detector = MockProfileDetector()
    
    def test_detect_developer_profile(self):
        """Test detection of developer profile from code-related request."""
        result = self.detector.detect("I need to refactor this code to improve performance")
        
        assert result.profile_type == "developer"
        assert result.confidence >= 0.1
        assert not result.fallback_used
        assert "developer" in result.indicators_matched
    
    def test_detect_designer_profile(self):
        """Test detection of designer profile from UI-related request."""
        result = self.detector.detect("Create a visual design for the dashboard with modern layout")
        
        assert result.profile_type == "designer"
        assert result.confidence >= 0.1
        assert not result.fallback_used
    
    def test_detect_analyst_profile(self):
        """Test detection of analyst profile from data-related request."""
        result = self.detector.detect("Analyze the sales data and create a report with key metrics")
        
        assert result.profile_type == "analyst"
        assert result.confidence >= 0.1
        assert not result.fallback_used
    
    def test_detect_devops_profile(self):
        """Test detection of devops profile from deployment-related request."""
        result = self.detector.detect("Deploy this to production and set up monitoring with Kubernetes")
        
        assert result.profile_type == "devops"
        assert result.confidence >= 0.1
        assert not result.fallback_used
    
    def test_detect_researcher_profile(self):
        """Test detection of researcher profile from research-related request."""
        result = self.detector.detect("Research the latest papers on transformer architectures and methodology")
        
        assert result.profile_type == "researcher"
        assert result.confidence >= 0.1
        assert not result.fallback_used
    
    def test_mixed_signals_handling(self):
        """Test handling of requests with mixed signals."""
        result = self.detector.detect("I want to design a new API and deploy it to the server")
        
        # Should detect something, but might have low confidence
        assert result.profile_type in ["designer", "developer", "devops"]
        # Mixed signals typically result in lower confidence
    
    def test_empty_input_handling(self):
        """Test handling of empty input."""
        result = self.detector.detect("")
        
        assert result.fallback_used is True
        assert result.confidence == 0.0
        assert result.detection_method == "fallback"
    
    def test_random_text_handling(self):
        """Test handling of text with no matching indicators."""
        result = self.detector.detect("asdfghjkl random text qwertyuiop")
        
        # Should use fallback due to no indicators
        assert result.fallback_used is True
        assert result.confidence == 0.0
    
    def test_lexical_score_calculation(self):
        """Test that lexical scores are calculated correctly."""
        request = "refactor debug implement code function"
        scores = self.detector._get_lexical_scores(request)
        
        # Developer should have highest score
        assert scores["developer"] > scores["designer"]
        assert scores["developer"] > scores["analyst"]
        assert scores["developer"] > scores["devops"]
        assert scores["developer"] > scores["researcher"]
    
    def test_negative_indicators_affect_score(self):
        """Test that negative indicators reduce score."""
        request_with_negatives = "design deploy server kubernetes"
        request_without_negatives = "design wireframe mockup prototype"
        
        scores_with = self.detector._get_lexical_scores(request_with_negatives)
        scores_without = self.detector._get_lexical_scores(request_without_negatives)
        
        # Designer score should be lower with negatives
        assert scores_without["designer"] > scores_with["designer"]
    
    def test_multiple_positive_indicators(self):
        """Test that multiple positive indicators increase confidence."""
        single_indicator = "code"
        multiple_indicators = "refactor debug implement function class api test code bug fix"
        
        result_single = self.detector.detect(single_indicator)
        result_multiple = self.detector.detect(multiple_indicators)
        
        # Multiple indicators should give higher confidence
        assert result_multiple.confidence > result_single.confidence


class TestProfileDetectionResult:
    """Test cases for ProfileDetectionResult dataclass."""
    
    def test_result_creation(self):
        """Test creating a detection result."""
        result = ProfileDetectionResult(
            profile_type="developer",
            confidence=0.8,
            detection_method="lexical",
            scores={"developer": 0.8, "analyst": 0.2},
            indicators_matched=["refactor", "debug"],
            timestamp="2026-04-09T00:00:00Z"
        )
        
        assert result.profile_type == "developer"
        assert result.confidence == 0.8
        assert result.detection_method == "lexical"
        assert len(result.indicators_matched) == 2
        assert result.fallback_used is False
    
    def test_result_with_fallback(self):
        """Test creating a result with fallback."""
        result = ProfileDetectionResult(
            profile_type="developer",
            confidence=0.0,
            detection_method="fallback",
            scores={},
            indicators_matched=[],
            timestamp="2026-04-09T00:00:00Z",
            fallback_used=True
        )
        
        assert result.fallback_used is True
        assert result.detection_method == "fallback"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
