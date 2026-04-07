"""
Self-Evolution Engine for TITAN Protocol.

ITEM-FEEDBACK-02: Self-Evolution Engine Implementation

This module provides the self-evolution capabilities for the TITAN Protocol,
enabling the system to automatically analyze successful patterns and
propose new skills based on observed behaviors.

Components:
- SkillDraft: Represents a proposed skill generated from patterns
- EvolutionStats: Statistics about the evolution process
- ValidationResult: Result of validating a skill draft
- SelfEvolutionEngine: Main engine for pattern analysis and skill generation

Key Features:
- Pattern analysis from successful sessions
- Skill draft generation from patterns
- Validation of drafts before proposal
- Human approval workflow (auto_propose_skills: false by default)
- Event emission for SKILL_DRAFT_CREATED, SKILL_APPROVED, SKILL_REJECTED

Author: TITAN Protocol Team
Version: 1.0.0
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, TYPE_CHECKING
import logging
import uuid
import json

if TYPE_CHECKING:
    from src.events.event_bus import EventBus
    from src.skills.skill_library import SkillLibrary
    from src.storage.backend import StorageBackend

from .pattern_extractor import Pattern, PatternExtractor


@dataclass
class SkillDraft:
    """
    Represents a proposed skill generated from successful patterns.
    
    A SkillDraft is created when a pattern with high reusability is
    identified and converted into a potential skill. It goes through
    validation and approval before becoming an actual skill.
    
    Attributes:
        draft_id: Unique identifier for this draft
        pattern_source: ID of the pattern that generated this draft
        proposed_skill_id: Suggested skill ID for the final skill
        description: Description of what this skill does
        applicable_to: List of task types this skill applies to
        required_tools: List of tools required by this skill
        role_hints: List of roles that would use this skill
        prompt_template: Optional prompt template for the skill
        validation_chain: List of validators for skill execution
        confidence: Confidence score for this draft (0.0-1.0)
        status: Current status (DRAFT, PROPOSED, APPROVED, REJECTED)
        created_at: When the draft was created
        rejection_reason: Reason for rejection if rejected
    
    Example:
        >>> draft = SkillDraft(
        ...     pattern_source="pat-abc123",
        ...     proposed_skill_id="auto_ast_chunking",
        ...     description="Automatically chunk code using AST analysis",
        ...     applicable_to=["AUDIT_CODE", "REVIEW_CODE"],
        ...     confidence=0.85
        ... )
    """
    draft_id: str = field(default_factory=lambda: f"draft-{uuid.uuid4().hex[:8]}")
    pattern_source: str = ""
    proposed_skill_id: str = ""
    description: str = ""
    applicable_to: List[str] = field(default_factory=list)
    required_tools: List[str] = field(default_factory=list)
    role_hints: List[str] = field(default_factory=list)
    prompt_template: Optional[str] = None
    validation_chain: List[str] = field(default_factory=list)
    confidence: float = 0.0
    status: str = "DRAFT"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    rejection_reason: Optional[str] = None
    
    def __post_init__(self):
        """Validate skill draft after initialization."""
        # Ensure confidence is within bounds
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be between 0.0 and 1.0, got {self.confidence}")
        
        # Ensure status is valid
        valid_statuses = ["DRAFT", "PROPOSED", "APPROVED", "REJECTED"]
        if self.status not in valid_statuses:
            raise ValueError(f"status must be one of {valid_statuses}, got {self.status}")
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert skill draft to dictionary for serialization.
        
        Returns:
            Dictionary representation of the skill draft
        """
        return {
            "draft_id": self.draft_id,
            "pattern_source": self.pattern_source,
            "proposed_skill_id": self.proposed_skill_id,
            "description": self.description,
            "applicable_to": self.applicable_to,
            "required_tools": self.required_tools,
            "role_hints": self.role_hints,
            "prompt_template": self.prompt_template,
            "validation_chain": self.validation_chain,
            "confidence": self.confidence,
            "status": self.status,
            "created_at": self.created_at,
            "rejection_reason": self.rejection_reason
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SkillDraft':
        """
        Create a SkillDraft from a dictionary.
        
        Args:
            data: Dictionary containing skill draft data
            
        Returns:
            SkillDraft instance
        """
        return cls(
            draft_id=data.get("draft_id", f"draft-{uuid.uuid4().hex[:8]}"),
            pattern_source=data.get("pattern_source", ""),
            proposed_skill_id=data.get("proposed_skill_id", ""),
            description=data.get("description", ""),
            applicable_to=data.get("applicable_to", []),
            required_tools=data.get("required_tools", []),
            role_hints=data.get("role_hints", []),
            prompt_template=data.get("prompt_template"),
            validation_chain=data.get("validation_chain", []),
            confidence=data.get("confidence", 0.0),
            status=data.get("status", "DRAFT"),
            created_at=data.get("created_at", datetime.utcnow().isoformat() + "Z"),
            rejection_reason=data.get("rejection_reason")
        )
    
    def is_ready_for_proposal(self) -> bool:
        """
        Check if this draft is ready to be proposed.
        
        Returns:
            True if the draft has all required fields and confidence >= 0.7
        """
        return (
            self.status == "DRAFT" and
            self.confidence >= 0.7 and
            bool(self.proposed_skill_id) and
            bool(self.description) and
            len(self.applicable_to) > 0
        )
    
    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"SkillDraft(draft_id={self.draft_id!r}, "
            f"skill_id={self.proposed_skill_id!r}, "
            f"status={self.status!r}, "
            f"confidence={self.confidence:.2f})"
        )


@dataclass
class EvolutionStats:
    """
    Statistics about the self-evolution process.
    
    Tracks metrics about pattern analysis, draft generation,
    and skill creation over time.
    
    Attributes:
        patterns_analyzed: Total patterns analyzed
        drafts_generated: Total drafts generated
        drafts_approved: Total drafts approved
        drafts_rejected: Total drafts rejected
        skills_created: Total skills created from drafts
        last_analysis: Timestamp of last analysis run
    """
    patterns_analyzed: int = 0
    drafts_generated: int = 0
    drafts_approved: int = 0
    drafts_rejected: int = 0
    skills_created: int = 0
    last_analysis: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.
        
        Returns:
            Dictionary representation
        """
        return {
            "patterns_analyzed": self.patterns_analyzed,
            "drafts_generated": self.drafts_generated,
            "drafts_approved": self.drafts_approved,
            "drafts_rejected": self.drafts_rejected,
            "skills_created": self.skills_created,
            "last_analysis": self.last_analysis
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'EvolutionStats':
        """
        Create from dictionary.
        
        Args:
            data: Dictionary containing stats data
            
        Returns:
            EvolutionStats instance
        """
        return cls(
            patterns_analyzed=data.get("patterns_analyzed", 0),
            drafts_generated=data.get("drafts_generated", 0),
            drafts_approved=data.get("drafts_approved", 0),
            drafts_rejected=data.get("drafts_rejected", 0),
            skills_created=data.get("skills_created", 0),
            last_analysis=data.get("last_analysis", "")
        )
    
    def approval_rate(self) -> float:
        """
        Calculate the approval rate.
        
        Returns:
            Approval rate (0.0-1.0) or 0.0 if no drafts
        """
        total = self.drafts_approved + self.drafts_rejected
        if total == 0:
            return 0.0
        return self.drafts_approved / total


@dataclass
class ValidationResult:
    """
    Result of validating a skill draft.
    
    Contains the validation outcome along with any issues found
    and suggestions for improvement.
    
    Attributes:
        valid: Whether the draft passed validation
        issues: List of issues found during validation
        suggestions: List of suggestions for improvement
    """
    valid: bool = False
    issues: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.
        
        Returns:
            Dictionary representation
        """
        return {
            "valid": self.valid,
            "issues": self.issues,
            "suggestions": self.suggestions
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ValidationResult':
        """
        Create from dictionary.
        
        Args:
            data: Dictionary containing validation result data
            
        Returns:
            ValidationResult instance
        """
        return cls(
            valid=data.get("valid", False),
            issues=data.get("issues", []),
            suggestions=data.get("suggestions", [])
        )


class SelfEvolutionEngine:
    """
    Main engine for self-evolution of the TITAN Protocol skill catalog.
    
    The SelfEvolutionEngine analyzes successful sessions to identify
    reusable patterns and generates skill proposals that can be
    approved and added to the skill library.
    
    Features:
    - Pattern analysis from successful sessions
    - Skill draft generation from patterns
    - Validation of drafts before proposal
    - Human approval workflow (auto_propose_skills: false by default)
    - Event emission for SKILL_DRAFT_CREATED, SKILL_APPROVED, SKILL_REJECTED
    
    Integration:
        - EventBus: For skill evolution events
        - SkillLibrary: For registering approved skills
        - PatternExtractor: For pattern extraction
        - StorageBackend: For persisting drafts and stats
    
    Example:
        >>> from src.events import EventBus
        >>> from src.skills import SkillLibrary
        >>> from src.evolution import PatternExtractor
        >>> 
        >>> event_bus = EventBus()
        >>> skill_library = SkillLibrary(config={}, event_bus=event_bus)
        >>> pattern_extractor = PatternExtractor(config={}, feedback_store=feedback, session_store=storage)
        >>> 
        >>> engine = SelfEvolutionEngine(
        ...     config={"auto_propose_skills": False},
        ...     pattern_extractor=pattern_extractor,
        ...     skill_library=skill_library,
        ...     event_bus=event_bus
        ... )
        >>> 
        >>> # Analyze patterns from last 7 days
        >>> from datetime import timedelta
        >>> patterns = engine.analyze_successful_patterns(timedelta(days=7))
        >>> 
        >>> # Generate skill draft from a pattern
        >>> if patterns:
        ...     draft = engine.extract_skill_candidate(patterns[0])
        ...     result = engine.validate_skill_draft(draft)
        ...     if result.valid:
        ...         proposal_id = engine.propose_skill(draft)
    """
    
    # Storage paths
    DRAFTS_PATH = "evolution/drafts"
    STATS_PATH = "evolution/stats.json"
    
    def __init__(
        self,
        config: Dict[str, Any],
        pattern_extractor: PatternExtractor,
        skill_library: 'SkillLibrary',
        event_bus: 'EventBus'
    ):
        """
        Initialize the SelfEvolutionEngine.
        
        Args:
            config: Configuration dictionary with options:
                - auto_propose_skills: Auto-propose valid drafts (default: False)
                - min_confidence: Minimum confidence for draft proposal (default: 0.7)
                - analysis_window_days: Default analysis window (default: 7)
                - min_patterns_for_skill: Minimum patterns to generate skill (default: 3)
            pattern_extractor: PatternExtractor instance
            skill_library: SkillLibrary instance for skill registration
            event_bus: EventBus instance for event emission
        """
        self.config = config
        self.pattern_extractor = pattern_extractor
        self.skill_library = skill_library
        self.event_bus = event_bus
        
        # Configuration defaults
        self._auto_propose = config.get("auto_propose_skills", False)
        self._min_confidence = config.get("min_confidence", 0.7)
        self._analysis_window_days = config.get("analysis_window_days", 7)
        self._min_patterns_for_skill = config.get("min_patterns_for_skill", 3)
        self._reusability_threshold = config.get("reusability_threshold", 0.7)
        
        # Internal state
        self._pending_proposals: Dict[str, SkillDraft] = {}
        self._stats = EvolutionStats()
        
        self._logger = logging.getLogger(__name__)
        
        # Load existing state
        self._load_state()
    
    def analyze_successful_patterns(self, window: timedelta) -> List[Pattern]:
        """
        Analyze successful sessions to identify reusable patterns.
        
        Finds sessions within the specified time window that have
        high success rates and extracts patterns from them.
        
        Args:
            window: Time window to analyze (e.g., timedelta(days=7))
            
        Returns:
            List of Pattern objects with high reusability scores
        """
        # Get successful sessions from the window
        sessions = self._get_successful_sessions(window)
        
        if not sessions:
            self._logger.info("No successful sessions found in the analysis window")
            return []
        
        # Find common patterns across sessions
        patterns = self.pattern_extractor.find_common_patterns(sessions)
        
        # Update stats
        self._stats.patterns_analyzed += len(patterns)
        self._stats.last_analysis = datetime.utcnow().isoformat() + "Z"
        self._save_state()
        
        self._logger.info(
            f"Analyzed {len(sessions)} sessions, found {len(patterns)} patterns"
        )
        
        return patterns
    
    def extract_skill_candidate(self, pattern: Pattern) -> SkillDraft:
        """
        Extract a skill candidate from a successful pattern.
        
        Converts a pattern into a skill draft with proposed
        attributes based on the pattern's characteristics.
        
        Args:
            pattern: Pattern to convert to a skill draft
            
        Returns:
            SkillDraft generated from the pattern
        """
        # Generate skill ID from pattern name
        skill_id = self._generate_skill_id(pattern)
        
        # Extract task types from pattern context
        applicable_to = self._extract_applicable_tasks(pattern)
        
        # Generate description
        description = self._generate_description(pattern)
        
        # Calculate confidence based on pattern metrics
        confidence = self._calculate_draft_confidence(pattern)
        
        # Generate role hints
        role_hints = self._infer_role_hints(pattern)
        
        # Generate validation chain
        validation_chain = self._generate_validation_chain(pattern)
        
        draft = SkillDraft(
            pattern_source=pattern.pattern_id,
            proposed_skill_id=skill_id,
            description=description,
            applicable_to=applicable_to,
            required_tools=pattern.components,
            role_hints=role_hints,
            validation_chain=validation_chain,
            confidence=confidence,
            status="DRAFT"
        )
        
        # Update stats
        self._stats.drafts_generated += 1
        self._save_state()
        
        # Emit SKILL_DRAFT_CREATED event
        self._emit_draft_created_event(draft)
        
        self._logger.info(
            f"Generated skill draft {draft.draft_id} from pattern {pattern.pattern_id}"
        )
        
        return draft
    
    def validate_skill_draft(self, draft: SkillDraft) -> ValidationResult:
        """
        Validate a skill draft before proposal.
        
        Checks the draft for completeness, consistency, and
        potential issues before it can be proposed.
        
        Args:
            draft: SkillDraft to validate
            
        Returns:
            ValidationResult with validation outcome
        """
        issues: List[str] = []
        suggestions: List[str] = []
        
        # Check required fields
        if not draft.proposed_skill_id:
            issues.append("Missing proposed_skill_id")
        elif not self._is_valid_skill_id(draft.proposed_skill_id):
            issues.append(f"Invalid skill ID format: {draft.proposed_skill_id}")
            suggestions.append("Use lowercase letters, numbers, and underscores only")
        
        if not draft.description:
            issues.append("Missing description")
            suggestions.append("Add a clear description of what the skill does")
        elif len(draft.description) < 20:
            issues.append("Description too short")
            suggestions.append("Provide a more detailed description (at least 20 characters)")
        
        if not draft.applicable_to:
            issues.append("No task types specified")
            suggestions.append("Specify at least one task type this skill applies to")
        
        # Check confidence level
        if draft.confidence < self._min_confidence:
            issues.append(f"Confidence {draft.confidence:.2f} below minimum {self._min_confidence}")
            suggestions.append("Wait for more pattern data to increase confidence")
        
        # Check for duplicate skills
        if draft.proposed_skill_id:
            existing = self.skill_library.get_skill(draft.proposed_skill_id)
            if existing:
                issues.append(f"Skill already exists: {draft.proposed_skill_id}")
                suggestions.append("Choose a different skill ID or update the existing skill")
        
        # Check for conflicts with existing drafts
        for pending_id, pending_draft in self._pending_proposals.items():
            if pending_draft.proposed_skill_id == draft.proposed_skill_id:
                issues.append(f"Pending proposal already exists for skill ID: {draft.proposed_skill_id}")
                suggestions.append("Review and approve/reject the existing proposal first")
                break
        
        # Determine validity
        valid = len(issues) == 0
        
        return ValidationResult(
            valid=valid,
            issues=issues,
            suggestions=suggestions
        )
    
    def propose_skill(self, draft: SkillDraft) -> str:
        """
        Propose a skill draft for approval.
        
        Validates the draft and adds it to the pending proposals
        queue for human review.
        
        Args:
            draft: SkillDraft to propose
            
        Returns:
            Proposal ID (same as draft_id)
            
        Raises:
            ValueError: If draft fails validation
        """
        # Validate draft
        result = self.validate_skill_draft(draft)
        if not result.valid:
            raise ValueError(f"Draft validation failed: {'; '.join(result.issues)}")
        
        # Update status
        draft.status = "PROPOSED"
        
        # Add to pending proposals
        self._pending_proposals[draft.draft_id] = draft
        
        # Save draft to storage
        self._save_draft(draft)
        
        # Emit SKILL_DRAFT_CREATED event (if not already emitted)
        self._emit_draft_created_event(draft)
        
        self._logger.info(
            f"Proposed skill draft {draft.draft_id} for approval"
        )
        
        return draft.draft_id
    
    def get_evolution_stats(self) -> EvolutionStats:
        """
        Get statistics about the evolution process.
        
        Returns:
            EvolutionStats with current metrics
        """
        return self._stats
    
    def get_pending_proposals(self) -> List[SkillDraft]:
        """
        Get all pending skill proposals awaiting approval.
        
        Returns:
            List of SkillDraft objects with status PROPOSED
        """
        return [
            draft for draft in self._pending_proposals.values()
            if draft.status == "PROPOSED"
        ]
    
    def approve_proposal(self, draft_id: str) -> bool:
        """
        Approve a pending skill proposal.
        
        Creates the actual skill in the skill library and
        removes the draft from pending proposals.
        
        Args:
            draft_id: ID of the draft to approve
            
        Returns:
            True if approval was successful, False otherwise
        """
        draft = self._pending_proposals.get(draft_id)
        if not draft:
            self._logger.warning(f"Draft not found: {draft_id}")
            return False
        
        if draft.status != "PROPOSED":
            self._logger.warning(f"Draft is not in PROPOSED status: {draft_id}")
            return False
        
        try:
            # Import Skill here to avoid circular imports
            from src.skills.skill import Skill, ReusablePattern
            
            # Create ReusablePattern from draft
            pattern = ReusablePattern(
                pattern_name=f"auto_{draft.proposed_skill_id}",
                implementation=draft.description,
                validation_chain=draft.validation_chain
            )
            
            # Create Skill from draft
            skill = Skill(
                skill_id=draft.proposed_skill_id,
                description=draft.description,
                applicable_to=draft.applicable_to,
                reusable_patterns=[pattern],
                role_hints=draft.role_hints,
                required_tools=draft.required_tools,
                prompt_template=draft.prompt_template,
                validation_chain=draft.validation_chain,
                metadata={
                    "auto_generated": True,
                    "pattern_source": draft.pattern_source,
                    "confidence": draft.confidence,
                    "created_at": datetime.utcnow().isoformat() + "Z"
                }
            )
            
            # Register skill
            self.skill_library.register_skill(skill)
            
            # Update draft status
            draft.status = "APPROVED"
            
            # Update stats
            self._stats.drafts_approved += 1
            self._stats.skills_created += 1
            self._save_state()
            
            # Remove from pending proposals
            del self._pending_proposals[draft_id]
            
            # Save updated draft
            self._save_draft(draft)
            
            # Emit SKILL_APPROVED event
            self._emit_skill_approved_event(draft, skill)
            
            self._logger.info(
                f"Approved skill draft {draft_id}, created skill {skill.skill_id}"
            )
            
            return True
            
        except Exception as e:
            self._logger.error(f"Failed to approve draft {draft_id}: {e}")
            return False
    
    def reject_proposal(self, draft_id: str, reason: str) -> bool:
        """
        Reject a pending skill proposal.
        
        Marks the draft as rejected and removes it from pending proposals.
        
        Args:
            draft_id: ID of the draft to reject
            reason: Reason for rejection
            
        Returns:
            True if rejection was successful, False otherwise
        """
        draft = self._pending_proposals.get(draft_id)
        if not draft:
            self._logger.warning(f"Draft not found: {draft_id}")
            return False
        
        if draft.status != "PROPOSED":
            self._logger.warning(f"Draft is not in PROPOSED status: {draft_id}")
            return False
        
        # Update draft status
        draft.status = "REJECTED"
        draft.rejection_reason = reason
        
        # Update stats
        self._stats.drafts_rejected += 1
        self._save_state()
        
        # Remove from pending proposals
        del self._pending_proposals[draft_id]
        
        # Save updated draft
        self._save_draft(draft)
        
        # Emit SKILL_REJECTED event
        self._emit_skill_rejected_event(draft, reason)
        
        self._logger.info(
            f"Rejected skill draft {draft_id}: {reason}"
        )
        
        return True
    
    def _get_successful_sessions(self, window: timedelta) -> List[str]:
        """
        Get successful sessions from the time window.
        
        Args:
            window: Time window to search
            
        Returns:
            List of session IDs
        """
        # Calculate window boundary
        cutoff = datetime.utcnow() - window
        cutoff_str = cutoff.isoformat() + "Z"
        
        sessions: List[str] = []
        
        try:
            # List all sessions
            session_paths = self.pattern_extractor.session_store.list(
                f"{self.pattern_extractor.SESSIONS_PATH}/"
            )
            
            for path in session_paths:
                if path.endswith("/session.json"):
                    try:
                        data = self.pattern_extractor.session_store.load_json(path)
                        
                        # Check timestamp
                        timestamp = data.get("created_at", data.get("timestamp", ""))
                        if timestamp and timestamp >= cutoff_str:
                            # Check success rate
                            success_rate = data.get("success_rate", 0.0)
                            if success_rate >= self.pattern_extractor._min_success_rate:
                                # Extract session ID from path
                                session_id = path.split("/")[-2]
                                sessions.append(session_id)
                    except Exception as e:
                        self._logger.debug(f"Failed to load session {path}: {e}")
        except Exception as e:
            self._logger.warning(f"Failed to list sessions: {e}")
        
        return sessions
    
    def _generate_skill_id(self, pattern: Pattern) -> str:
        """
        Generate a skill ID from a pattern.
        
        Args:
            pattern: Pattern to generate ID from
            
        Returns:
            Generated skill ID
        """
        # Use pattern name if available
        if pattern.pattern_name:
            # Clean up pattern name
            skill_id = pattern.pattern_name.lower()
            skill_id = skill_id.replace(" ", "_").replace("-", "_")
            skill_id = "".join(c for c in skill_id if c.isalnum() or c == "_")
            return f"auto_{skill_id}"
        
        # Generate from components
        if pattern.components:
            components_str = "_".join(pattern.components[:2])
            components_str = components_str.lower()
            components_str = "".join(c for c in components_str if c.isalnum() or c == "_")
            return f"auto_{components_str}"
        
        # Fallback to hash-based ID
        return f"auto_skill_{pattern.get_hash()}"
    
    def _extract_applicable_tasks(self, pattern: Pattern) -> List[str]:
        """
        Extract applicable task types from a pattern.
        
        Args:
            pattern: Pattern to extract tasks from
            
        Returns:
            List of task types
        """
        tasks: List[str] = []
        
        # Check context requirements
        context = pattern.context_requirements
        
        if "task_type" in context:
            task_type = context["task_type"]
            if task_type and task_type != "unknown":
                tasks.append(task_type)
        
        # Infer from pattern type
        pattern_type = context.get("type", "")
        
        if pattern_type == "skill_application":
            tasks.append("GENERAL_TASK")
        elif pattern_type == "tool_sequence":
            tasks.append("CODE_PROCESSING")
        elif pattern_type == "decision":
            tasks.append("DECISION_MAKING")
        
        # Default if no tasks found
        if not tasks:
            tasks.append("GENERAL")
        
        return list(set(tasks))
    
    def _generate_description(self, pattern: Pattern) -> str:
        """
        Generate a description from a pattern.
        
        Args:
            pattern: Pattern to generate description from
            
        Returns:
            Generated description
        """
        if pattern.description:
            return pattern.description
        
        # Generate from components
        components = pattern.components
        if components:
            tools_str = ", ".join(components[:3])
            if len(components) > 3:
                tools_str += f" (+{len(components) - 3} more)"
            return f"Auto-generated skill using: {tools_str}"
        
        # Generic description
        return f"Auto-generated skill from pattern: {pattern.pattern_name}"
    
    def _calculate_draft_confidence(self, pattern: Pattern) -> float:
        """
        Calculate confidence score for a skill draft.
        
        Args:
            pattern: Pattern to calculate confidence from
            
        Returns:
            Confidence score (0.0-1.0)
        """
        # Base confidence from pattern reusability
        confidence = pattern.reusability_score * 0.5
        
        # Boost for multiple sessions
        session_boost = min(0.3, len(pattern.session_ids) * 0.05)
        confidence += session_boost
        
        # Boost for high success rate
        if pattern.success_rate >= 0.9:
            confidence += 0.1
        elif pattern.success_rate >= 0.8:
            confidence += 0.05
        
        # Reduce for too many components (complexity)
        if len(pattern.components) > 5:
            confidence -= 0.1
        
        return round(min(1.0, max(0.0, confidence)), 3)
    
    def _infer_role_hints(self, pattern: Pattern) -> List[str]:
        """
        Infer role hints from a pattern.
        
        Args:
            pattern: Pattern to infer roles from
            
        Returns:
            List of inferred role hints
        """
        roles: List[str] = []
        
        # Check context for task type
        context = pattern.context_requirements
        task_type = context.get("task_type", "").upper()
        
        # Map task types to roles
        role_mapping = {
            "AUDIT_CODE": ["senior-developer", "architect"],
            "REVIEW_CODE": ["reviewer", "senior-developer"],
            "DEBUG": ["debugger", "senior-developer"],
            "DOCUMENTATION": ["technical-writer", "developer"],
            "TEST": ["qa-engineer", "developer"],
            "GENERAL": ["developer"]
        }
        
        for key, mapped_roles in role_mapping.items():
            if key in task_type:
                roles.extend(mapped_roles)
                break
        
        # Default role if no match
        if not roles:
            roles.append("developer")
        
        return list(set(roles))
    
    def _generate_validation_chain(self, pattern: Pattern) -> List[str]:
        """
        Generate validation chain for a skill draft.
        
        Args:
            pattern: Pattern to generate validation from
            
        Returns:
            List of validation steps
        """
        validators: List[str] = ["basic_check"]
        
        # Add validators based on components
        for component in pattern.components:
            if "parser" in component.lower():
                validators.append("parse_validation")
            elif "api" in component.lower():
                validators.append("api_validation")
            elif "file" in component.lower():
                validators.append("file_validation")
        
        # Add output validation
        validators.append("output_check")
        
        return list(set(validators))
    
    def _is_valid_skill_id(self, skill_id: str) -> bool:
        """
        Check if a skill ID is valid.
        
        Args:
            skill_id: Skill ID to validate
            
        Returns:
            True if valid, False otherwise
        """
        if not skill_id:
            return False
        
        # Check format: lowercase letters, numbers, underscores
        import re
        return bool(re.match(r'^[a-z][a-z0-9_]*$', skill_id))
    
    def _emit_draft_created_event(self, draft: SkillDraft) -> None:
        """
        Emit SKILL_DRAFT_CREATED event.
        
        Args:
            draft: Draft that was created
        """
        from src.events.event_bus import Event, EventSeverity
        
        event = Event(
            event_type="SKILL_DRAFT_CREATED",
            data={
                "draft_id": draft.draft_id,
                "proposed_skill_id": draft.proposed_skill_id,
                "pattern_source": draft.pattern_source,
                "confidence": draft.confidence,
                "applicable_to": draft.applicable_to
            },
            severity=EventSeverity.INFO,
            source="SelfEvolutionEngine"
        )
        self.event_bus.emit(event)
    
    def _emit_skill_approved_event(self, draft: SkillDraft, skill) -> None:
        """
        Emit SKILL_APPROVED event.
        
        Args:
            draft: Draft that was approved
            skill: Skill that was created
        """
        from src.events.event_bus import Event, EventSeverity
        
        event = Event(
            event_type="SKILL_APPROVED",
            data={
                "draft_id": draft.draft_id,
                "skill_id": skill.skill_id,
                "pattern_source": draft.pattern_source,
                "confidence": draft.confidence
            },
            severity=EventSeverity.INFO,
            source="SelfEvolutionEngine"
        )
        self.event_bus.emit(event)
    
    def _emit_skill_rejected_event(self, draft: SkillDraft, reason: str) -> None:
        """
        Emit SKILL_REJECTED event.
        
        Args:
            draft: Draft that was rejected
            reason: Reason for rejection
        """
        from src.events.event_bus import Event, EventSeverity
        
        event = Event(
            event_type="SKILL_REJECTED",
            data={
                "draft_id": draft.draft_id,
                "proposed_skill_id": draft.proposed_skill_id,
                "reason": reason
            },
            severity=EventSeverity.WARN,
            source="SelfEvolutionEngine"
        )
        self.event_bus.emit(event)
    
    def _save_draft(self, draft: SkillDraft) -> None:
        """
        Save a draft to storage.
        
        Args:
            draft: Draft to save
        """
        # Use session_store from pattern_extractor
        storage = self.pattern_extractor.session_store
        path = f"{self.DRAFTS_PATH}/{draft.draft_id}.json"
        storage.save_json(path, draft.to_dict())
    
    def _load_draft(self, draft_id: str) -> Optional[SkillDraft]:
        """
        Load a draft from storage.
        
        Args:
            draft_id: Draft ID to load
            
        Returns:
            SkillDraft or None if not found
        """
        storage = self.pattern_extractor.session_store
        path = f"{self.DRAFTS_PATH}/{draft_id}.json"
        
        try:
            data = storage.load_json(path)
            return SkillDraft.from_dict(data)
        except Exception:
            return None
    
    def _save_state(self) -> None:
        """
        Save evolution state to storage.
        """
        storage = self.pattern_extractor.session_store
        storage.save_json(self.STATS_PATH, self._stats.to_dict())
    
    def _load_state(self) -> None:
        """
        Load evolution state from storage.
        """
        storage = self.pattern_extractor.session_store
        
        # Load stats
        try:
            data = storage.load_json(self.STATS_PATH)
            self._stats = EvolutionStats.from_dict(data)
        except Exception:
            self._stats = EvolutionStats()
        
        # Load pending proposals
        try:
            draft_paths = storage.list(f"{self.DRAFTS_PATH}/")
            for path in draft_paths:
                if path.endswith(".json"):
                    try:
                        data = storage.load_json(path)
                        draft = SkillDraft.from_dict(data)
                        if draft.status == "PROPOSED":
                            self._pending_proposals[draft.draft_id] = draft
                    except Exception as e:
                        self._logger.debug(f"Failed to load draft {path}: {e}")
        except Exception:
            pass
    
    def run_evolution_cycle(self, window: timedelta = None) -> Dict[str, Any]:
        """
        Run a complete evolution cycle.
        
        Analyzes patterns, generates drafts, validates them,
        and optionally auto-proposes valid drafts.
        
        Args:
            window: Time window to analyze (default from config)
            
        Returns:
            Dictionary with cycle results
        """
        if window is None:
            window = timedelta(days=self._analysis_window_days)
        
        results = {
            "patterns_found": 0,
            "drafts_generated": 0,
            "drafts_proposed": 0,
            "errors": []
        }
        
        try:
            # Analyze patterns
            patterns = self.analyze_successful_patterns(window)
            results["patterns_found"] = len(patterns)
            
            if len(patterns) < self._min_patterns_for_skill:
                self._logger.info(
                    f"Not enough patterns for skill generation: "
                    f"{len(patterns)} < {self._min_patterns_for_skill}"
                )
                return results
            
            # Generate drafts from top patterns
            drafts_generated = 0
            drafts_proposed = 0
            
            for pattern in patterns:
                if pattern.reusability_score >= self._reusability_threshold:
                    try:
                        draft = self.extract_skill_candidate(pattern)
                        drafts_generated += 1
                        
                        # Validate and optionally auto-propose
                        validation = self.validate_skill_draft(draft)
                        
                        if validation.valid:
                            if self._auto_propose:
                                self.propose_skill(draft)
                                drafts_proposed += 1
                        else:
                            self._logger.info(
                                f"Draft {draft.draft_id} validation failed: "
                                f"{validation.issues}"
                            )
                    except Exception as e:
                        results["errors"].append(f"Pattern {pattern.pattern_id}: {str(e)}")
            
            results["drafts_generated"] = drafts_generated
            results["drafts_proposed"] = drafts_proposed
            
        except Exception as e:
            results["errors"].append(f"Evolution cycle error: {str(e)}")
            self._logger.error(f"Evolution cycle failed: {e}")
        
        return results
