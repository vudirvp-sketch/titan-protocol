"""
Self-Evolution Module for TITAN Protocol.

ITEM-FEEDBACK-02: Self-Evolution Engine Implementation

This module provides self-evolution capabilities for the TITAN Protocol,
enabling the system to automatically analyze successful patterns and
propose new skills based on observed behaviors.

Key Components:
    Pattern Extraction:
    - Pattern: Represents an extracted behavioral pattern
    - PatternExtractor: Extracts patterns from successful sessions
    
    Skill Evolution:
    - SkillDraft: Proposed skill generated from patterns
    - EvolutionStats: Statistics about the evolution process
    - ValidationResult: Result of validating a skill draft
    - SelfEvolutionEngine: Main engine for pattern analysis and skill generation

Features:
- Pattern extraction from successful sessions
- Clustering of similar patterns
- Skill draft generation from patterns
- Validation of drafts before proposal
- Human approval workflow (auto_propose_skills: false by default)
- Event emission for SKILL_DRAFT_CREATED, SKILL_APPROVED, SKILL_REJECTED

Usage:
    >>> from src.evolution import SelfEvolutionEngine, PatternExtractor
    >>> from src.events import EventBus
    >>> from src.skills import SkillLibrary
    >>> from src.storage import LocalStorageBackend
    >>> from src.feedback import FeedbackLoop
    >>> from datetime import timedelta
    >>> 
    >>> # Initialize components
    >>> event_bus = EventBus()
    >>> storage = LocalStorageBackend(base_path="./.titan/storage")
    >>> feedback_loop = FeedbackLoop(config={}, event_bus=event_bus, storage_backend=storage)
    >>> skill_library = SkillLibrary(config={}, event_bus=event_bus)
    >>> 
    >>> # Create pattern extractor
    >>> extractor = PatternExtractor(
    ...     config={},
    ...     feedback_store=feedback_loop,
    ...     session_store=storage
    ... )
    >>> 
    >>> # Create evolution engine
    >>> engine = SelfEvolutionEngine(
    ...     config={"auto_propose_skills": False},
    ...     pattern_extractor=extractor,
    ...     skill_library=skill_library,
    ...     event_bus=event_bus
    ... )
    >>> 
    >>> # Analyze patterns from last 7 days
    >>> patterns = engine.analyze_successful_patterns(timedelta(days=7))
    >>> print(f"Found {len(patterns)} reusable patterns")
    >>> 
    >>> # Generate skill draft from a pattern
    >>> if patterns:
    ...     draft = engine.extract_skill_candidate(patterns[0])
    ...     result = engine.validate_skill_draft(draft)
    ...     if result.valid:
    ...         proposal_id = engine.propose_skill(draft)
    ...         print(f"Proposed skill: {proposal_id}")
    >>> 
    >>> # Review pending proposals
    >>> pending = engine.get_pending_proposals()
    >>> for draft in pending:
    ...     print(f"Draft: {draft.proposed_skill_id} (confidence: {draft.confidence:.2f})")
    ... 
    >>> # Approve or reject proposals
    >>> engine.approve_proposal(pending[0].draft_id)
    >>> # or
    >>> engine.reject_proposal(pending[0].draft_id, "Not suitable for general use")

Algorithm:
    Pattern Extraction:
    - Analyzes session tool/skill usage sequences
    - Identifies successful decision patterns
    - Clusters similar patterns together
    - Calculates reusability scores
    
    Skill Draft Generation:
    - Converts high-reusability patterns to drafts
    - Infers applicable task types
    - Generates role hints from context
    - Calculates confidence scores
    
    Validation:
    - Checks required fields
    - Validates skill ID format
    - Detects duplicates
    - Checks confidence thresholds
    
    Approval Workflow:
    - Drafts start in DRAFT status
    - Valid drafts move to PROPOSED
    - Human review required for APPROVED/REJECTED
    - Approved drafts become skills in library

Events Emitted:
    - SKILL_DRAFT_CREATED: When a new draft is generated
    - SKILL_APPROVED: When a draft is approved and skill created
    - SKILL_REJECTED: When a draft is rejected

Integration:
    - EventBus: For skill evolution events
    - SkillLibrary: For registering approved skills
    - StorageBackend: For persisting drafts and stats
    - FeedbackLoop: For accessing session feedback

Author: TITAN Protocol Team
Version: 1.0.0
"""

# Pattern extraction
from src.evolution.pattern_extractor import (
    Pattern,
    PatternExtractor
)

# Self-evolution engine
from src.evolution.self_evolution import (
    SkillDraft,
    EvolutionStats,
    ValidationResult,
    SelfEvolutionEngine
)


__all__ = [
    # Pattern extraction
    'Pattern',
    'PatternExtractor',
    
    # Self-evolution
    'SkillDraft',
    'EvolutionStats',
    'ValidationResult',
    'SelfEvolutionEngine',
]


# Module metadata
__version__ = '1.0.0'
__author__ = 'TITAN Protocol Team'
