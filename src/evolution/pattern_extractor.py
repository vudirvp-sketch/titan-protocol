"""
Pattern Extractor for TITAN Protocol Self-Evolution.

ITEM-FEEDBACK-02: Pattern Extraction from Successful Sessions

This module provides pattern extraction capabilities for the self-evolution
system, analyzing successful sessions to identify reusable patterns that
can be converted into skills.

Components:
- Pattern: Dataclass representing an extracted behavioral pattern
- PatternExtractor: Main class for extracting and clustering patterns

Key Features:
- Extract patterns from successful sessions
- Find common patterns across multiple sessions
- Calculate pattern reusability scores
- Cluster similar patterns together

Author: TITAN Protocol Team
Version: 1.0.0
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Optional, TYPE_CHECKING
import logging
import uuid
import hashlib
import json

if TYPE_CHECKING:
    from src.storage.backend import StorageBackend
    from src.feedback.feedback_loop import FeedbackLoop


@dataclass
class Pattern:
    """
    Represents an extracted behavioral pattern from successful sessions.
    
    A Pattern captures a reusable solution approach that was successful
    in one or more sessions, with metrics on its success rate and
    reusability potential.
    
    Attributes:
        pattern_id: Unique identifier for this pattern
        pattern_name: Human-readable name for the pattern
        description: Detailed description of the pattern's approach
        session_ids: List of sessions where this pattern was successful
        success_rate: Ratio of successful applications (0.0-1.0)
        reusability_score: Calculated reusability potential (0.0-1.0)
        components: List of tools/skills used in this pattern
        context_requirements: Required context for pattern application
        created_at: When the pattern was first extracted
        updated_at: When the pattern was last updated
    
    Example:
        >>> pattern = Pattern(
        ...     pattern_name="ast_based_chunking",
        ...     description="Use AST parsing to identify code chunk boundaries",
        ...     session_ids=["sess-001", "sess-002"],
        ...     success_rate=0.95,
        ...     components=["ast_parser", "semantic_analyzer"]
        ... )
    """
    pattern_id: str = field(default_factory=lambda: f"pat-{uuid.uuid4().hex[:8]}")
    pattern_name: str = ""
    description: str = ""
    session_ids: List[str] = field(default_factory=list)
    success_rate: float = 0.0
    reusability_score: float = 0.0
    components: List[str] = field(default_factory=list)
    context_requirements: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    def __post_init__(self):
        """Validate pattern after initialization."""
        # Ensure success_rate is within bounds
        if not 0.0 <= self.success_rate <= 1.0:
            raise ValueError(f"success_rate must be between 0.0 and 1.0, got {self.success_rate}")
        
        # Ensure reusability_score is within bounds
        if not 0.0 <= self.reusability_score <= 1.0:
            raise ValueError(f"reusability_score must be between 0.0 and 1.0, got {self.reusability_score}")
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert pattern to dictionary for serialization.
        
        Returns:
            Dictionary representation of the pattern
        """
        return {
            "pattern_id": self.pattern_id,
            "pattern_name": self.pattern_name,
            "description": self.description,
            "session_ids": self.session_ids,
            "success_rate": self.success_rate,
            "reusability_score": self.reusability_score,
            "components": self.components,
            "context_requirements": self.context_requirements,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Pattern':
        """
        Create a Pattern from a dictionary.
        
        Args:
            data: Dictionary containing pattern data
            
        Returns:
            Pattern instance
        """
        return cls(
            pattern_id=data.get("pattern_id", f"pat-{uuid.uuid4().hex[:8]}"),
            pattern_name=data.get("pattern_name", ""),
            description=data.get("description", ""),
            session_ids=data.get("session_ids", []),
            success_rate=data.get("success_rate", 0.0),
            reusability_score=data.get("reusability_score", 0.0),
            components=data.get("components", []),
            context_requirements=data.get("context_requirements", {}),
            created_at=data.get("created_at", datetime.utcnow().isoformat() + "Z"),
            updated_at=data.get("updated_at", datetime.utcnow().isoformat() + "Z")
        )
    
    def get_hash(self) -> str:
        """
        Get a unique hash for this pattern.
        
        Returns:
            SHA256 hash of the pattern's key attributes
        """
        content = json.dumps({
            "pattern_name": self.pattern_name,
            "components": sorted(self.components),
            "context_requirements": self.context_requirements
        }, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def merge_with(self, other: 'Pattern') -> 'Pattern':
        """
        Merge this pattern with another similar pattern.
        
        Args:
            other: Another Pattern to merge with
            
        Returns:
            New merged Pattern
        """
        # Combine session IDs (unique)
        merged_sessions = list(set(self.session_ids + other.session_ids))
        
        # Weight success rate by session count
        total_sessions = len(self.session_ids) + len(other.session_ids)
        if total_sessions > 0:
            merged_success_rate = (
                (self.success_rate * len(self.session_ids) +
                 other.success_rate * len(other.session_ids)) /
                total_sessions
            )
        else:
            merged_success_rate = 0.0
        
        # Combine components (unique)
        merged_components = list(set(self.components + other.components))
        
        # Merge context requirements
        merged_context = {**self.context_requirements, **other.context_requirements}
        
        return Pattern(
            pattern_name=self.pattern_name or other.pattern_name,
            description=self.description or other.description,
            session_ids=merged_sessions,
            success_rate=merged_success_rate,
            reusability_score=max(self.reusability_score, other.reusability_score),
            components=merged_components,
            context_requirements=merged_context
        )
    
    def __hash__(self) -> int:
        """Make pattern hashable for use in sets and dicts."""
        return hash(self.pattern_id)
    
    def __eq__(self, other: object) -> bool:
        """Check equality based on pattern_id."""
        if not isinstance(other, Pattern):
            return NotImplemented
        return self.pattern_id == other.pattern_id
    
    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"Pattern(pattern_id={self.pattern_id!r}, "
            f"name={self.pattern_name!r}, "
            f"sessions={len(self.session_ids)}, "
            f"success_rate={self.success_rate:.2f})"
        )


class PatternExtractor:
    """
    Extracts and analyzes patterns from successful sessions.
    
    The PatternExtractor analyzes session data to identify successful
    behavioral patterns that can be reused and potentially converted
    into skills.
    
    Features:
    - Extract patterns from individual sessions
    - Find common patterns across multiple sessions
    - Calculate pattern reusability scores
    - Cluster similar patterns together
    
    Integration:
        - FeedbackLoop: For accessing session feedback data
        - StorageBackend: For accessing session data
        
    Example:
        >>> from src.feedback import FeedbackLoop
        >>> from src.storage import LocalStorageBackend
        >>> 
        >>> storage = LocalStorageBackend(base_path="./.titan/storage")
        >>> feedback_loop = FeedbackLoop(config={}, event_bus=bus, storage_backend=storage)
        >>> 
        >>> extractor = PatternExtractor(
        ...     config={},
        ...     feedback_store=feedback_loop,
        ...     session_store=storage
        ... )
        >>> 
        >>> # Extract patterns from a session
        >>> patterns = extractor.extract_from_session("sess-123")
        >>> 
        >>> # Find common patterns across sessions
        >>> common = extractor.find_common_patterns(["sess-001", "sess-002", "sess-003"])
    """
    
    # Storage paths
    PATTERNS_PATH = "patterns"
    SESSIONS_PATH = "sessions"
    
    def __init__(
        self,
        config: Dict[str, Any],
        feedback_store: 'FeedbackLoop',
        session_store: 'StorageBackend'
    ):
        """
        Initialize the PatternExtractor.
        
        Args:
            config: Configuration dictionary with options:
                - min_session_success_rate: Minimum success rate for session inclusion (default: 0.8)
                - min_pattern_occurrences: Minimum occurrences for a pattern (default: 2)
                - reusability_threshold: Minimum reusability score (default: 0.7)
                - similarity_threshold: Threshold for pattern clustering (default: 0.8)
            feedback_store: FeedbackLoop instance for accessing feedback
            session_store: StorageBackend instance for accessing session data
        """
        self.config = config
        self.feedback_store = feedback_store
        self.session_store = session_store
        
        # Configuration defaults
        self._min_success_rate = config.get("min_session_success_rate", 0.8)
        self._min_pattern_occurrences = config.get("min_pattern_occurrences", 2)
        self._reusability_threshold = config.get("reusability_threshold", 0.7)
        self._similarity_threshold = config.get("similarity_threshold", 0.8)
        
        # Pattern cache
        self._pattern_cache: Dict[str, Pattern] = {}
        
        self._logger = logging.getLogger(__name__)
    
    def extract_from_session(self, session_id: str) -> List[Pattern]:
        """
        Extract patterns from a single session.
        
        Analyzes the session data to identify successful patterns,
        including tool usage sequences, skill applications, and
        decision patterns.
        
        Args:
            session_id: The session ID to extract patterns from
            
        Returns:
            List of Pattern objects extracted from the session
        """
        patterns: List[Pattern] = []
        
        # Load session data
        session_data = self._load_session_data(session_id)
        if not session_data:
            self._logger.warning(f"Session not found: {session_id}")
            return patterns
        
        # Check session success rate
        session_success_rate = session_data.get("success_rate", 0.0)
        if session_success_rate < self._min_success_rate:
            self._logger.debug(
                f"Session {session_id} below success rate threshold: "
                f"{session_success_rate:.2f} < {self._min_success_rate}"
            )
            return patterns
        
        # Extract tool usage patterns
        tool_patterns = self._extract_tool_patterns(session_id, session_data)
        patterns.extend(tool_patterns)
        
        # Extract skill application patterns
        skill_patterns = self._extract_skill_patterns(session_id, session_data)
        patterns.extend(skill_patterns)
        
        # Extract decision patterns
        decision_patterns = self._extract_decision_patterns(session_id, session_data)
        patterns.extend(decision_patterns)
        
        # Calculate reusability for each pattern
        for pattern in patterns:
            pattern.reusability_score = self.calculate_pattern_reusability(pattern)
        
        self._logger.info(
            f"Extracted {len(patterns)} patterns from session {session_id}"
        )
        
        return patterns
    
    def find_common_patterns(self, sessions: List[str]) -> List[Pattern]:
        """
        Find patterns that are successful across multiple sessions.
        
        Analyzes patterns from multiple sessions to identify those
        that appear consistently and have high reusability scores.
        
        Args:
            sessions: List of session IDs to analyze
            
        Returns:
            List of common Pattern objects with reusability >= 0.7
        """
        all_patterns: List[Pattern] = []
        
        for session_id in sessions:
            patterns = self.extract_from_session(session_id)
            all_patterns.extend(patterns)
        
        # Group by similarity
        grouped = self._cluster_patterns(all_patterns)
        
        # Filter by reusability (>= 0.7)
        return [
            p for p in grouped 
            if self.calculate_pattern_reusability(p) >= 0.7
        ]
    
    def calculate_pattern_reusability(self, pattern: Pattern) -> float:
        """
        Calculate the reusability score for a pattern.
        
        The reusability score is based on:
        - Number of sessions where the pattern was successful
        - Success rate of the pattern
        - Complexity of the pattern (fewer components = more reusable)
        
        Formula:
            reusability = (session_factor * 0.4) + (success_factor * 0.4) + (simplicity_factor * 0.2)
        
        Where:
            session_factor = min(1.0, session_count / 5)
            success_factor = pattern.success_rate
            simplicity_factor = 1.0 / max(1, component_count / 3)
        
        Args:
            pattern: The Pattern to calculate reusability for
            
        Returns:
            Reusability score between 0.0 and 1.0
        """
        if not pattern.session_ids:
            return 0.0
        
        # Session factor: more sessions = higher reusability
        session_count = len(pattern.session_ids)
        session_factor = min(1.0, session_count / 5.0)
        
        # Success factor: higher success rate = higher reusability
        success_factor = pattern.success_rate
        
        # Simplicity factor: fewer components = more reusable
        component_count = len(pattern.components)
        simplicity_factor = 1.0 / max(1.0, component_count / 3.0)
        
        # Weighted combination
        reusability = (
            session_factor * 0.4 +
            success_factor * 0.4 +
            simplicity_factor * 0.2
        )
        
        return round(min(1.0, reusability), 3)
    
    def _cluster_patterns(self, patterns: List[Pattern]) -> List[Pattern]:
        """
        Cluster similar patterns together.
        
        Groups patterns that are similar based on their components
        and context requirements, merging them into consolidated patterns.
        
        Args:
            patterns: List of patterns to cluster
            
        Returns:
            List of clustered/merged patterns
        """
        if not patterns:
            return []
        
        # Group patterns by similarity
        clusters: List[List[Pattern]] = []
        
        for pattern in patterns:
            # Find a cluster this pattern fits into
            found_cluster = False
            
            for cluster in clusters:
                # Check similarity with first pattern in cluster
                if self._calculate_similarity(pattern, cluster[0]) >= self._similarity_threshold:
                    cluster.append(pattern)
                    found_cluster = True
                    break
            
            # Create new cluster if no match found
            if not found_cluster:
                clusters.append([pattern])
        
        # Merge patterns within each cluster
        merged_patterns: List[Pattern] = []
        
        for cluster in clusters:
            if len(cluster) == 1:
                merged_patterns.append(cluster[0])
            else:
                # Merge all patterns in the cluster
                merged = cluster[0]
                for pattern in cluster[1:]:
                    merged = merged.merge_with(pattern)
                merged_patterns.append(merged)
        
        return merged_patterns
    
    def _calculate_similarity(self, pattern1: Pattern, pattern2: Pattern) -> float:
        """
        Calculate similarity between two patterns.
        
        Uses Jaccard similarity on components and pattern name matching.
        
        Args:
            pattern1: First pattern
            pattern2: Second pattern
            
        Returns:
            Similarity score between 0.0 and 1.0
        """
        # Component similarity (Jaccard)
        components1 = set(pattern1.components)
        components2 = set(pattern2.components)
        
        if components1 or components2:
            component_similarity = (
                len(components1 & components2) /
                len(components1 | components2)
            )
        else:
            component_similarity = 1.0 if not (components1 or components2) else 0.0
        
        # Name similarity
        name_similarity = 1.0 if pattern1.pattern_name == pattern2.pattern_name else 0.0
        
        # Context similarity
        context_keys1 = set(pattern1.context_requirements.keys())
        context_keys2 = set(pattern2.context_requirements.keys())
        
        if context_keys1 or context_keys2:
            context_similarity = (
                len(context_keys1 & context_keys2) /
                len(context_keys1 | context_keys2)
            )
        else:
            context_similarity = 1.0
        
        # Weighted combination
        similarity = (
            component_similarity * 0.5 +
            name_similarity * 0.3 +
            context_similarity * 0.2
        )
        
        return similarity
    
    def _load_session_data(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Load session data from storage.
        
        Args:
            session_id: Session ID to load
            
        Returns:
            Session data dictionary or None if not found
        """
        path = f"{self.SESSIONS_PATH}/{session_id}/session.json"
        
        try:
            return self.session_store.load_json(path)
        except Exception as e:
            self._logger.debug(f"Failed to load session {session_id}: {e}")
            return None
    
    def _extract_tool_patterns(self, session_id: str, session_data: Dict) -> List[Pattern]:
        """
        Extract tool usage patterns from session data.
        
        Args:
            session_id: Session ID
            session_data: Session data dictionary
            
        Returns:
            List of tool-based patterns
        """
        patterns: List[Pattern] = []
        
        # Get tool usage history
        tool_history = session_data.get("tool_history", [])
        if not tool_history:
            return patterns
        
        # Group consecutive tool uses into patterns
        current_sequence: List[str] = []
        sequence_success_count = 0
        sequence_total_count = 0
        
        for entry in tool_history:
            tool_name = entry.get("tool", "")
            success = entry.get("success", False)
            
            if tool_name:
                current_sequence.append(tool_name)
                sequence_total_count += 1
                if success:
                    sequence_success_count += 1
        
        # Create pattern if we have a meaningful sequence
        if len(current_sequence) >= 2:
            success_rate = sequence_success_count / sequence_total_count if sequence_total_count > 0 else 0.0
            
            pattern = Pattern(
                pattern_name=f"tool_sequence_{len(current_sequence)}_tools",
                description=f"Tool sequence: {' -> '.join(current_sequence[:5])}",
                session_ids=[session_id],
                success_rate=success_rate,
                components=current_sequence,
                context_requirements={
                    "type": "tool_sequence",
                    "length": len(current_sequence)
                }
            )
            patterns.append(pattern)
        
        return patterns
    
    def _extract_skill_patterns(self, session_id: str, session_data: Dict) -> List[Pattern]:
        """
        Extract skill application patterns from session data.
        
        Args:
            session_id: Session ID
            session_data: Session data dictionary
            
        Returns:
            List of skill-based patterns
        """
        patterns: List[Pattern] = []
        
        # Get skill usage history
        skill_history = session_data.get("skill_history", [])
        if not skill_history:
            return patterns
        
        # Track skill combinations that were successful
        skill_combinations: Dict[str, List[str]] = {}
        skill_success: Dict[str, int] = {}
        skill_total: Dict[str, int] = {}
        
        for entry in skill_history:
            skill_id = entry.get("skill_id", "")
            task_type = entry.get("task_type", "unknown")
            success = entry.get("success", False)
            
            if skill_id:
                key = f"{task_type}:{skill_id}"
                skill_combinations[key] = skill_combinations.get(key, [])
                skill_total[key] = skill_total.get(key, 0) + 1
                if success:
                    skill_success[key] = skill_success.get(key, 0) + 1
        
        # Create patterns from successful skill applications
        for key, total in skill_total.items():
            success_count = skill_success.get(key, 0)
            success_rate = success_count / total if total > 0 else 0.0
            
            if success_rate >= self._min_success_rate:
                task_type, skill_id = key.split(":", 1)
                
                pattern = Pattern(
                    pattern_name=f"skill_pattern_{skill_id}",
                    description=f"Successful application of {skill_id} for {task_type}",
                    session_ids=[session_id],
                    success_rate=success_rate,
                    components=[skill_id],
                    context_requirements={
                        "type": "skill_application",
                        "task_type": task_type
                    }
                )
                patterns.append(pattern)
        
        return patterns
    
    def _extract_decision_patterns(self, session_id: str, session_data: Dict) -> List[Pattern]:
        """
        Extract decision patterns from session data.
        
        Args:
            session_id: Session ID
            session_data: Session data dictionary
            
        Returns:
            List of decision-based patterns
        """
        patterns: List[Pattern] = []
        
        # Get decision history
        decisions = session_data.get("decisions", [])
        if not decisions:
            return patterns
        
        # Track decision patterns
        decision_types: Dict[str, Dict[str, Any]] = {}
        
        for decision in decisions:
            decision_type = decision.get("type", "")
            outcome = decision.get("outcome", "")
            success = decision.get("success", False)
            
            if decision_type and outcome:
                key = f"{decision_type}:{outcome}"
                
                if key not in decision_types:
                    decision_types[key] = {
                        "count": 0,
                        "success": 0,
                        "context": decision.get("context", {})
                    }
                
                decision_types[key]["count"] += 1
                if success:
                    decision_types[key]["success"] += 1
        
        # Create patterns from successful decision patterns
        for key, data in decision_types.items():
            success_rate = data["success"] / data["count"] if data["count"] > 0 else 0.0
            
            if success_rate >= self._min_success_rate and data["count"] >= 2:
                decision_type, outcome = key.split(":", 1)
                
                pattern = Pattern(
                    pattern_name=f"decision_pattern_{decision_type}",
                    description=f"Decision pattern: {decision_type} -> {outcome}",
                    session_ids=[session_id],
                    success_rate=success_rate,
                    components=[decision_type],
                    context_requirements={
                        "type": "decision",
                        "outcome": outcome,
                        "context": data["context"]
                    }
                )
                patterns.append(pattern)
        
        return patterns
    
    def save_pattern(self, pattern: Pattern) -> str:
        """
        Save a pattern to storage.
        
        Args:
            pattern: Pattern to save
            
        Returns:
            Pattern ID
        """
        path = f"{self.PATTERNS_PATH}/{pattern.pattern_id}.json"
        self.session_store.save_json(path, pattern.to_dict())
        
        # Update cache
        self._pattern_cache[pattern.pattern_id] = pattern
        
        self._logger.info(f"Saved pattern {pattern.pattern_id}")
        return pattern.pattern_id
    
    def load_pattern(self, pattern_id: str) -> Optional[Pattern]:
        """
        Load a pattern from storage.
        
        Args:
            pattern_id: Pattern ID to load
            
        Returns:
            Pattern or None if not found
        """
        # Check cache first
        if pattern_id in self._pattern_cache:
            return self._pattern_cache[pattern_id]
        
        path = f"{self.PATTERNS_PATH}/{pattern_id}.json"
        
        try:
            data = self.session_store.load_json(path)
            pattern = Pattern.from_dict(data)
            self._pattern_cache[pattern_id] = pattern
            return pattern
        except Exception as e:
            self._logger.debug(f"Failed to load pattern {pattern_id}: {e}")
            return None
    
    def list_patterns(self) -> List[str]:
        """
        List all pattern IDs.
        
        Returns:
            List of pattern IDs
        """
        try:
            paths = self.session_store.list(f"{self.PATTERNS_PATH}/")
            return [
                p.split("/")[-1].replace(".json", "")
                for p in paths
                if p.endswith(".json")
            ]
        except Exception:
            return []
