"""
Skill and ReusablePattern dataclasses for TITAN Protocol.

ITEM-SKILL-01: Skill data model with catalog support.

This module defines the core data structures for the skill catalog:
- ReusablePattern: A named, validated implementation pattern
- Skill: A skill with task type applicability and role hints

Author: TITAN FUSE Team
Version: 3.5.0
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
import hashlib
import json


@dataclass
class ReusablePattern:
    """
    A reusable implementation pattern that can be shared across skills.

    Patterns encapsulate proven solutions with validation chains
    that ensure consistent application across different contexts.

    Attributes:
        pattern_name: Unique identifier for the pattern
        implementation: Description of the implementation approach
        validation_chain: List of validators that must pass for pattern use

    Example:
        >>> pattern = ReusablePattern(
        ...     pattern_name="chunk_boundary_detection",
        ...     implementation="AST_based+semantic_markers",
        ...     validation_chain=["ast_parser", "schema_check"]
        ... )
        >>> pattern.to_dict()
        {'pattern_name': 'chunk_boundary_detection', ...}
    """
    pattern_name: str
    implementation: str
    validation_chain: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the pattern to a dictionary representation.

        Returns:
            Dictionary containing all pattern attributes
        """
        return {
            "pattern_name": self.pattern_name,
            "implementation": self.implementation,
            "validation_chain": self.validation_chain
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ReusablePattern':
        """
        Create a ReusablePattern from a dictionary.

        Args:
            data: Dictionary containing pattern data

        Returns:
            ReusablePattern instance
        """
        return cls(
            pattern_name=data["pattern_name"],
            implementation=data.get("implementation", ""),
            validation_chain=data.get("validation_chain", [])
        )

    def __hash__(self) -> int:
        """Make pattern hashable for use in sets and dicts."""
        return hash((self.pattern_name, self.implementation, tuple(self.validation_chain)))

    def __eq__(self, other: object) -> bool:
        """Check equality based on pattern_name."""
        if not isinstance(other, ReusablePattern):
            return NotImplemented
        return self.pattern_name == other.pattern_name


@dataclass
class Skill:
    """
    A skill definition with task type applicability and role hints.

    Skills define capabilities that can be matched to tasks based on
    task type and role hints. They include reusable patterns, validation
    chains, and UI component references.

    Attributes:
        skill_id: Unique identifier for the skill
        description: Human-readable description of the skill's purpose
        applicable_to: List of task types this skill can handle
        reusable_patterns: List of reusable implementation patterns
        ui_component: Optional path to a UI component for this skill
        role_hints: List of roles that typically use this skill
        required_tools: List of tools required for this skill
        prompt_template: Optional path to a prompt template file
        validation_chain: List of validators for skill execution
        metadata: Additional metadata about the skill

    Selection Priority (handled by SkillLibrary):
        1. Exact task_type match + role match
        2. Exact task_type match
        3. Partial task_type match + role match
        4. Partial task_type match

    Example:
        >>> skill = Skill(
        ...     skill_id="rlm_deterministic_chunking",
        ...     description="Process large files without hallucinations",
        ...     applicable_to=["AUDIT_CODE", "REVIEW_PLAN"],
        ...     role_hints=["senior-python-dev", "architect"]
        ... )
        >>> skill.is_applicable("AUDIT_CODE")
        True
        >>> skill.matches_role("architect")
        True
    """
    skill_id: str
    description: str
    applicable_to: List[str] = field(default_factory=list)
    reusable_patterns: List[ReusablePattern] = field(default_factory=list)
    ui_component: Optional[str] = None
    role_hints: List[str] = field(default_factory=list)
    required_tools: List[str] = field(default_factory=list)
    prompt_template: Optional[str] = None
    validation_chain: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_applicable(self, task_type: str) -> bool:
        """
        Check if this skill is applicable to a task type.

        Supports both exact matching and partial matching:
        - Exact: "AUDIT_CODE" matches "AUDIT_CODE"
        - Partial: "CODE" matches "AUDIT_CODE" or "CODE_REVIEW"

        Args:
            task_type: The task type to check

        Returns:
            True if the skill is applicable, False otherwise
        """
        if not task_type:
            return False

        task_type_upper = task_type.upper()

        # Check for exact match first
        for applicable in self.applicable_to:
            if applicable.upper() == task_type_upper:
                return True

        # Check for partial match (task_type is substring of applicable)
        for applicable in self.applicable_to:
            if task_type_upper in applicable.upper():
                return True
            # Also check reverse: applicable is substring of task_type
            if applicable.upper() in task_type_upper:
                return True

        return False

    def matches_role(self, role: str) -> bool:
        """
        Check if this skill matches a given role.

        Role matching is case-insensitive and supports partial matches.

        Args:
            role: The role to check

        Returns:
            True if the skill matches the role, False otherwise
        """
        if not role:
            return False

        role_lower = role.lower()

        for hint in self.role_hints:
            hint_lower = hint.lower()
            # Check both directions for partial matches
            if role_lower in hint_lower or hint_lower in role_lower:
                return True

        return False

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the skill to a dictionary representation.

        Returns:
            Dictionary containing all skill attributes
        """
        return {
            "skill_id": self.skill_id,
            "description": self.description,
            "applicable_to": self.applicable_to,
            "reusable_patterns": [p.to_dict() for p in self.reusable_patterns],
            "ui_component": self.ui_component,
            "role_hints": self.role_hints,
            "required_tools": self.required_tools,
            "prompt_template": self.prompt_template,
            "validation_chain": self.validation_chain,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Skill':
        """
        Create a Skill from a dictionary.

        Args:
            data: Dictionary containing skill data

        Returns:
            Skill instance
        """
        # Parse reusable patterns
        patterns = []
        for pattern_data in data.get("reusable_patterns", []):
            if isinstance(pattern_data, dict):
                patterns.append(ReusablePattern.from_dict(pattern_data))
            elif isinstance(pattern_data, ReusablePattern):
                patterns.append(pattern_data)

        return cls(
            skill_id=data["skill_id"],
            description=data.get("description", ""),
            applicable_to=data.get("applicable_to", []),
            reusable_patterns=patterns,
            ui_component=data.get("ui_component"),
            role_hints=data.get("role_hints", []),
            required_tools=data.get("required_tools", []),
            prompt_template=data.get("prompt_template"),
            validation_chain=data.get("validation_chain", []),
            metadata=data.get("metadata", {})
        )

    def get_hash(self) -> str:
        """
        Get a unique hash for this skill definition.

        Returns:
            SHA256 hash of the skill's serialized form
        """
        content = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def has_synergy(self) -> bool:
        """
        Check if this skill has synergy potential.

        A skill has synergy if it's applicable to 2 or more task types,
        indicating it can be reused across different contexts.

        Returns:
            True if applicable_to >= 2, False otherwise
        """
        return len(self.applicable_to) >= 2

    def __hash__(self) -> int:
        """Make skill hashable for use in sets and dicts."""
        return hash(self.skill_id)

    def __eq__(self, other: object) -> bool:
        """Check equality based on skill_id."""
        if not isinstance(other, Skill):
            return NotImplemented
        return self.skill_id == other.skill_id

    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"Skill(skill_id={self.skill_id!r}, applicable_to={self.applicable_to!r})"

    def __str__(self) -> str:
        """Human-readable string representation."""
        roles = ", ".join(self.role_hints[:3])
        if len(self.role_hints) > 3:
            roles += f" (+{len(self.role_hints) - 3})"
        return f"[{self.skill_id}] {self.description} (roles: {roles})"
