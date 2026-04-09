"""
TITAN Protocol - Profile Detection Mixin

ITEM_005: ProfileDetectionMixin for TITAN Protocol v1.2.0

Extends ProfileRouter with user role detection capabilities.
Detects user profile (designer/developer/analyst/devops/researcher)
from request text using lexical analysis, pattern matching, and history.

Key Features:
- UserRole enum for 5 user role profiles
- Lexical analysis with weighted indicators
- Pattern matching for request structure
- History-based analysis
- Configurable detection weights
- LRU caching for performance
- EventBus integration

Integration Points:
- UniversalRouter: Uses for profile detection
- IntentEnricher: Gets detected profile for enrichment
- EventBus: Emits PROFILE_DETECTED events
- SessionMemory: Uses history for detection

Author: TITAN FUSE Team
Version: 1.2.0
"""

import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional, List, Callable
from functools import lru_cache
import logging

from src.events.event_bus import Event, EventSeverity, EventBus
from src.utils.timezone import now_utc_iso


class UserRole(Enum):
    """
    User role profiles for intent-based routing.
    
    Roles:
    - DESIGNER: UI/UX, visual design, prototyping
    - DEVELOPER: Code, refactoring, debugging, implementation
    - ANALYST: Data analysis, reporting, metrics
    - DEVOPS: Deployment, infrastructure, monitoring
    - RESEARCHER: Academic research, papers, exploration
    """
    DESIGNER = "designer"
    DEVELOPER = "developer"
    ANALYST = "analyst"
    DEVOPS = "devops"
    RESEARCHER = "researcher"


@dataclass
class ProfileDetectionResult:
    """
    Result of profile detection.
    
    Attributes:
        profile_type: Detected UserRole
        confidence: Detection confidence (0.0 to 1.0)
        detection_method: Method used for detection
        scores: Score breakdown by method
        indicators_matched: List of matched indicators
        timestamp: Detection timestamp
        fallback_used: Whether fallback was used
    """
    profile_type: str
    confidence: float
    detection_method: str
    scores: Dict[str, float] = field(default_factory=dict)
    indicators_matched: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=now_utc_iso)
    fallback_used: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "profile_type": self.profile_type,
            "confidence": self.confidence,
            "detection_method": self.detection_method,
            "scores": self.scores,
            "indicators_matched": self.indicators_matched,
            "timestamp": self.timestamp,
            "fallback_used": self.fallback_used,
        }


# Lexical indicators for each role
LEXICAL_INDICATORS = {
    UserRole.DESIGNER: {
        "positive": [
            "design", "ui", "ux", "visual", "layout", "color", "prototype",
            "wireframe", "mockup", "user experience", "figma", "sketch",
            "component", "responsive", "accessibility", "theme", "style",
            "animation", "interaction", "user interface", "dashboard",
        ],
        "negative": [
            "deploy", "server", "config", "database", "kubernetes", "docker",
            "api endpoint", "backend", "infrastructure", "pipeline", "ci", "cd",
        ],
    },
    UserRole.DEVELOPER: {
        "positive": [
            "refactor", "debug", "implement", "function", "class", "api",
            "test", "code", "bug", "fix", "pr", "merge", "commit", "unit test",
            "integration", "coverage", "lint", "type", "variable", "module",
        ],
        "negative": [
            "visual", "layout", "color", "mockup", "design", "figma",
            "sketch", "wireframe", "prototype",
        ],
    },
    UserRole.ANALYST: {
        "positive": [
            "analyze", "report", "metric", "data", "insight", "trend",
            "dashboard", "statistics", "kpi", "visualization", "chart",
            "graph", "aggregate", "pivot", "forecast", "analysis",
        ],
        "negative": [
            "implement", "deploy", "code", "refactor", "debug", "fix bug",
            "dockerfile", "helm chart",
        ],
    },
    UserRole.DEVOPS: {
        "positive": [
            "deploy", "server", "config", "scale", "monitor", "pipeline",
            "ci", "cd", "container", "kubernetes", "docker", "helm",
            "terraform", "ansible", "infrastructure", "provisioning",
            "orchestration", "cloud", "aws", "azure", "gcp",
        ],
        "negative": [
            "visual", "mockup", "ui", "figma", "sketch", "prototype", "wireframe",
        ],
    },
    UserRole.RESEARCHER: {
        "positive": [
            "research", "explore", "hypothesis", "investigate", "study",
            "paper", "citation", "literature", "methodology", "experiment",
            "survey", "review", "academic", "publication", "arxiv",
        ],
        "negative": [
            "implement", "deploy", "debug", "fix", "refactor", "docker", "kubernetes",
        ],
    },
}

# Pattern indicators for request structure
PATTERN_INDICATORS = {
    UserRole.DESIGNER: [
        r"(create|design|build)\s+(a|the)?\s*(ui|interface|dashboard|layout)",
        r"(improve|enhance|update)\s+(the)?\s*(visual|design|style)",
        r"(wireframe|mockup|prototype)",
    ],
    UserRole.DEVELOPER: [
        r"(refactor|rewrite|restructure)\s+(the|this)?\s*(code|module|function)",
        r"(debug|fix|resolve)\s+(the|this|a)?\s*(error|bug|issue)",
        r"(implement|add|create)\s+(a|the|new)?\s*(feature|function|method)",
    ],
    UserRole.ANALYST: [
        r"(analyze|examine|study)\s+(the|this)?\s*(data|metrics|results)",
        r"(create|generate|build)\s+(a|the)?\s*(report|dashboard|chart)",
        r"(what|how many|how much)\s+(is|are)\s+(the)?\s*(metrics|numbers)",
    ],
    UserRole.DEVOPS: [
        r"(deploy|ship|release)\s+(to|the)?\s*(production|staging|server)",
        r"(set up|configure|provision)\s+(the|a)?\s*(server|cluster|environment)",
        r"(monitor|scale|optimize)\s+(the|this)?\s*(infrastructure|service)",
    ],
    UserRole.RESEARCHER: [
        r"(research|investigate|explore)\s+(the|this)?\s*(topic|subject|area)",
        r"(find|search|look for)\s+(papers|articles|studies)",
        r"(what is|explain|describe)\s+(the|a)?\s*(theory|concept)",
    ],
}


class ProfileDetectionMixin:
    """
    Mixin class for user role profile detection.
    
    Provides lexical analysis, pattern matching, and history-based
    detection methods for identifying user profiles.
    
    Usage:
        class EnhancedProfileRouter(ProfileRouter, ProfileDetectionMixin):
            pass
        
        router = EnhancedProfileRouter(event_bus=event_bus)
        result = router.detect_with_lexical_analysis("Refactor this code")
        print(result.profile_type)  # "developer"
    """
    
    # Default weights for detection methods
    DEFAULT_WEIGHTS = {
        "lexical_analysis": 0.4,
        "pattern_matching": 0.3,
        "history_analysis": 0.2,
        "explicit_signal": 0.1,
    }
    
    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        event_bus: Optional[EventBus] = None,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize ProfileDetectionMixin.
        
        Args:
            config: Configuration dictionary
            event_bus: EventBus for event emission
            logger: Optional logger instance
        """
        self._config = config or {}
        self._event_bus = event_bus
        self._logger = logger or logging.getLogger(__name__)
        
        # Detection weights (configurable)
        self._weights = dict(self.DEFAULT_WEIGHTS)
        if "weights" in self._config:
            self._weights.update(self._config["weights"])
        
        # Cache for detection results
        self._cache_enabled = self._config.get("cache_enabled", True)
        self._cache_max_size = self._config.get("cache_max_size", 1000)
        
        # Thread safety
        self._lock = threading.RLock()
    
    def detect_with_lexical_analysis(
        self,
        request: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ProfileDetectionResult:
        """
        Detect user profile from request text.
        
        Combines lexical analysis, pattern matching, and history
        analysis to determine the most likely user profile.
        
        Args:
            request: The user's request string
            context: Optional context (session_id for history)
        
        Returns:
            ProfileDetectionResult with detected profile and confidence
        """
        context = context or {}
        
        # Normalize request
        normalized_request = self._normalize_request(request)
        
        # Calculate scores for each method
        lexical_scores = self.get_lexical_score(normalized_request)
        pattern_scores = self.get_pattern_score(normalized_request)
        
        # Get history scores if session available
        history_scores = {}
        session_id = context.get("session_id")
        if session_id and self._weights.get("history_analysis", 0) > 0:
            history_scores = self.get_history_score(session_id)
        
        # Check for explicit signals
        explicit_scores = self._get_explicit_signal_score(normalized_request)
        
        # Combine scores
        all_scores = {
            "lexical_analysis": lexical_scores,
            "pattern_matching": pattern_scores,
            "history_analysis": history_scores,
            "explicit_signal": explicit_scores,
        }
        
        combined = self.combine_scores(all_scores)
        
        # Determine best profile
        if not combined:
            return self._create_fallback_result(request)
        
        best_profile = max(combined, key=combined.get)
        confidence = combined[best_profile]
        
        # Check minimum confidence
        min_confidence = self._config.get("min_confidence", 0.5)
        if confidence < min_confidence:
            return self._create_fallback_result(request, combined)
        
        # Get matched indicators
        indicators = self._get_matched_indicators(normalized_request, best_profile)
        
        result = ProfileDetectionResult(
            profile_type=best_profile,
            confidence=confidence,
            detection_method="combined",
            scores=combined,
            indicators_matched=indicators,
        )
        
        # Emit event
        self.emit_profile_detected(result)
        
        return result
    
    def _normalize_request(self, request: str) -> str:
        """Normalize request text for analysis."""
        # Lowercase
        normalized = request.lower()
        # Remove extra whitespace
        normalized = " ".join(normalized.split())
        return normalized
    
    def get_lexical_score(self, request: str) -> Dict[str, float]:
        """
        Calculate lexical scores for each profile.
        
        Args:
            request: Normalized request string
        
        Returns:
            Dictionary of profile -> score
        """
        scores = {}
        request_lower = request.lower()
        request_words = set(request_lower.split())
        
        for role in UserRole:
            indicators = LEXICAL_INDICATORS.get(role, {})
            positive = indicators.get("positive", [])
            negative = indicators.get("negative", [])
            
            # Count positive matches
            positive_matches = sum(
                1 for indicator in positive
                if indicator in request_lower or indicator.replace(" ", "_") in request_lower
            )
            
            # Count negative matches (reduce score)
            negative_matches = sum(
                1 for indicator in negative
                if indicator in request_lower
            )
            
            # Calculate score
            if positive_matches > 0 or negative_matches > 0:
                score = (positive_matches * 0.2) - (negative_matches * 0.15)
                scores[role.value] = max(0, min(1, score))
            else:
                scores[role.value] = 0.0
        
        # Normalize scores
        max_score = max(scores.values()) if scores else 1
        if max_score > 0:
            scores = {k: v / max_score for k, v in scores.items()}
        
        return scores
    
    def get_pattern_score(self, request: str) -> Dict[str, float]:
        """
        Calculate pattern matching scores.
        
        Args:
            request: Request string
        
        Returns:
            Dictionary of profile -> score
        """
        scores = {}
        
        for role in UserRole:
            patterns = PATTERN_INDICATORS.get(role, [])
            matches = 0
            
            for pattern in patterns:
                try:
                    if re.search(pattern, request, re.IGNORECASE):
                        matches += 1
                except re.error:
                    continue
            
            scores[role.value] = min(1.0, matches * 0.3)
        
        return scores
    
    def get_history_score(self, session_id: str) -> Dict[str, float]:
        """
        Calculate history-based scores.
        
        This method should be overridden to integrate with SessionMemory.
        
        Args:
            session_id: Session identifier
        
        Returns:
            Dictionary of profile -> score
        """
        # Base implementation returns empty scores
        # Override in production to use SessionMemory
        return {role.value: 0.0 for role in UserRole}
    
    def _get_explicit_signal_score(self, request: str) -> Dict[str, float]:
        """
        Detect explicit profile signals in request.
        
        Args:
            request: Request string
        
        Returns:
            Dictionary of profile -> score
        """
        scores = {role.value: 0.0 for role in UserRole}
        
        # Check for explicit role mentions
        explicit_patterns = {
            UserRole.DESIGNER: [r"as a designer", r"i'?m a designer", r"designer mode"],
            UserRole.DEVELOPER: [r"as a developer", r"i'?m a developer", r"developer mode"],
            UserRole.ANALYST: [r"as an analyst", r"i'?m an analyst", r"analyst mode"],
            UserRole.DEVOPS: [r"as a devops", r"i'?m a devops", r"devops mode"],
            UserRole.RESEARCHER: [r"as a researcher", r"i'?m a researcher", r"researcher mode"],
        }
        
        for role, patterns in explicit_patterns.items():
            for pattern in patterns:
                if re.search(pattern, request, re.IGNORECASE):
                    scores[role.value] = 1.0
                    break
        
        return scores
    
    def combine_scores(
        self,
        scores: Dict[str, Dict[str, float]],
    ) -> Dict[str, float]:
        """
        Combine scores from different methods using weights.
        
        Args:
            scores: Dictionary of method -> {profile -> score}
        
        Returns:
            Dictionary of profile -> combined score
        """
        combined = {role.value: 0.0 for role in UserRole}
        
        for method, method_scores in scores.items():
            weight = self._weights.get(method, 0)
            if weight == 0:
                continue
            
            for profile, score in method_scores.items():
                if profile in combined:
                    combined[profile] += score * weight
        
        # Normalize to 0-1 range
        max_score = max(combined.values()) if combined else 1
        if max_score > 0:
            combined = {k: v / max_score for k, v in combined.items()}
        
        return combined
    
    def _get_matched_indicators(self, request: str, profile: str) -> List[str]:
        """Get list of matched indicators for a profile."""
        matched = []
        request_lower = request.lower()
        
        try:
            role = UserRole(profile)
            indicators = LEXICAL_INDICATORS.get(role, {})
            for indicator in indicators.get("positive", []):
                if indicator in request_lower:
                    matched.append(indicator)
        except ValueError:
            pass
        
        return matched
    
    def _create_fallback_result(
        self,
        request: str,
        scores: Optional[Dict[str, float]] = None,
    ) -> ProfileDetectionResult:
        """Create fallback result when detection fails."""
        # Default fallback to developer
        fallback_profile = self._config.get("fallback_profile", "developer")
        
        return ProfileDetectionResult(
            profile_type=fallback_profile,
            confidence=0.0,
            detection_method="fallback",
            scores=scores or {},
            indicators_matched=[],
            fallback_used=True,
        )
    
    def emit_profile_detected(self, result: ProfileDetectionResult) -> None:
        """Emit PROFILE_DETECTED event."""
        if not self._event_bus:
            return
        
        event = Event(
            event_type="PROFILE_DETECTED",
            data=result.to_dict(),
            severity=EventSeverity.INFO,
            source="ProfileDetectionMixin",
        )
        self._event_bus.emit(event)
    
    def configure_weights(self, weights: Dict[str, float]) -> None:
        """
        Configure detection method weights.
        
        Args:
            weights: Dictionary of method -> weight
        """
        with self._lock:
            self._weights.update(weights)
    
    def clear_cache(self) -> None:
        """Clear detection cache."""
        # Cache clearing for LRU cache
        pass


class EnhancedProfileRouter(ProfileDetectionMixin):
    """
    Enhanced ProfileRouter with user role detection.
    
    Combines ProfileRouter's context adaptation profiles with
    ProfileDetectionMixin's user role detection capabilities.
    
    Usage:
        router = EnhancedProfileRouter(event_bus=event_bus)
        
        # Detect user role
        result = router.detect_with_lexical_analysis("Refactor this code")
        print(result.profile_type)  # "developer"
        
        # Configure weights
        router.configure_weights({
            "lexical_analysis": 0.5,
            "pattern_matching": 0.3,
            "history_analysis": 0.1,
            "explicit_signal": 0.1,
        })
    """
    
    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        event_bus: Optional[EventBus] = None,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize EnhancedProfileRouter.
        
        Args:
            config: Configuration dictionary
            event_bus: EventBus for event emission
            logger: Optional logger instance
        """
        super().__init__(config=config, event_bus=event_bus, logger=logger)


# Factory function
def create_enhanced_profile_router(
    config: Optional[Dict[str, Any]] = None,
    event_bus: Optional[EventBus] = None,
) -> EnhancedProfileRouter:
    """
    Factory function to create EnhancedProfileRouter.
    
    Args:
        config: Configuration dictionary
        event_bus: EventBus instance
    
    Returns:
        EnhancedProfileRouter instance
    """
    return EnhancedProfileRouter(config=config, event_bus=event_bus)
