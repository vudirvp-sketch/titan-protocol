"""
PolicyResolver for TITAN FUSE Protocol - EQUIP Stage.

ITEM-POLICY-01: PolicyResolver for EQUIP Stage

Implements policy resolution for skills during the EQUIP stage.
Resolves conflicts between skill requirements and policy constraints
to determine if a skill can be executed.

Key Features:
- Tool validation against allowed tools
- Role-based policy constraint checking
- Budget management and override detection
- Batch linting for multiple skills

Author: TITAN FUSE Team
Version: 1.0.0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Protocol

# Configure module logger
logger = logging.getLogger(__name__)


# =============================================================================
# Enums
# =============================================================================

class ConflictType(Enum):
    """
    Types of conflicts that can occur during policy resolution.
    
    Attributes:
        TOOL_NOT_ALLOWED: Required tool is not in the allowed_tools list
        ROLE_POLICY_MISMATCH: Role hints conflict with policy constraints
        BUDGET_EXCEEDED: Skill budget exceeds available budget
        STYLE_GUIDE_VIOLATION: Output format violates style guide rules
        SECURITY_POLICY_VIOLATION: Tool or action marked as unsafe
    """
    TOOL_NOT_ALLOWED = "required_tool not in allowed_tools"
    ROLE_POLICY_MISMATCH = "role_hints conflicts with constraints"
    BUDGET_EXCEEDED = "skill budget > available budget"
    STYLE_GUIDE_VIOLATION = "output format violates style guide"
    SECURITY_POLICY_VIOLATION = "tool marked as unsafe"


class ResolutionStatus(Enum):
    """
    Status of policy resolution for a skill.
    
    Attributes:
        ALLOWED: Skill can be executed without restrictions
        BLOCKED: Skill cannot be executed due to policy violations
        CONDITIONAL: Skill can be executed with conditions/approvals
    """
    ALLOWED = "ALLOWED"
    BLOCKED = "BLOCKED"
    CONDITIONAL = "CONDITIONAL"


# =============================================================================
# Constraint Protocol
# =============================================================================

class Constraint(Protocol):
    """
    Protocol for role-based constraints.
    
    A constraint defines a rule that must be satisfied for a skill
    to be allowed to execute within a specific role context.
    """
    
    name: str
    description: str
    
    def violates(self, skill: "Skill") -> bool:
        """
        Check if this constraint is violated by the skill.
        
        Args:
            skill: The skill to check against this constraint
            
        Returns:
            True if the constraint is violated, False otherwise
        """
        ...


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class Conflict:
    """
    Represents a policy conflict detected during resolution.
    
    Attributes:
        type: The type of conflict
        severity: Either "ERROR" (blocks execution) or "WARN" (warning only)
        details: Human-readable description of the conflict
        skill_id: ID of the skill that caused the conflict
    
    Example:
        >>> conflict = Conflict(
        ...     type=ConflictType.TOOL_NOT_ALLOWED,
        ...     severity="ERROR",
        ...     details="Tool 'bash' not in allowed_tools",
        ...     skill_id="skill-001"
        ... )
    """
    type: ConflictType
    severity: str  # "ERROR" or "WARN"
    details: str
    skill_id: str
    
    def __post_init__(self) -> None:
        """Validate severity is either ERROR or WARN."""
        if self.severity not in ("ERROR", "WARN"):
            raise ValueError(
                f"severity must be 'ERROR' or 'WARN', got '{self.severity}'"
            )
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the conflict to a dictionary representation.
        
        Returns:
            Dictionary with conflict details
        """
        return {
            "type": self.type.value,
            "severity": self.severity,
            "details": self.details,
            "skill_id": self.skill_id
        }


@dataclass
class ResolutionResult:
    """
    Result of policy resolution for a single skill.
    
    Contains the resolution status, any conflicts detected, warnings,
    required approvals, and overridden constraints.
    
    Attributes:
        skill_id: ID of the skill being resolved
        resolution: The resolution status (ALLOWED, BLOCKED, or CONDITIONAL)
        conflicts: List of conflicts detected during resolution
        warnings: List of warning messages (non-blocking issues)
        required_approvals: List of approvals needed for conditional execution
        overridden_constraints: List of constraint names that were overridden
    
    Example:
        >>> result = ResolutionResult(
        ...     skill_id="skill-001",
        ...     resolution=ResolutionStatus.ALLOWED,
        ...     conflicts=[],
        ...     warnings=["Minor style issue detected"]
        ... )
        >>> result.is_executable()
        True
    """
    skill_id: str
    resolution: ResolutionStatus
    conflicts: List[Conflict] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    required_approvals: List[str] = field(default_factory=list)
    overridden_constraints: List[str] = field(default_factory=list)
    
    def is_executable(self) -> bool:
        """
        Check if the skill can be executed based on resolution.
        
        A skill is executable if:
        - Resolution is ALLOWED, or
        - Resolution is CONDITIONAL (can execute with conditions)
        
        Returns:
            True if the skill can be executed, False otherwise
        """
        return self.resolution in (
            ResolutionStatus.ALLOWED,
            ResolutionStatus.CONDITIONAL
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the resolution result to a dictionary representation.
        
        Returns:
            Dictionary with all resolution details
        """
        return {
            "skill_id": self.skill_id,
            "resolution": self.resolution.value,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "warnings": self.warnings,
            "required_approvals": self.required_approvals,
            "overridden_constraints": self.overridden_constraints,
            "is_executable": self.is_executable()
        }


@dataclass
class Skill:
    """
    Simple representation of a skill for policy resolution.
    
    Contains the minimal information needed to evaluate a skill
    against policy constraints during the EQUIP stage.
    
    Attributes:
        skill_id: Unique identifier for the skill
        required_tools: List of tool names required by this skill
        role_hints: List of roles this skill is associated with
        estimated_tokens: Estimated token budget required by this skill
    
    Example:
        >>> skill = Skill(
        ...     skill_id="skill-001",
        ...     required_tools=["bash", "python"],
        ...     role_hints=["developer", "automation"],
        ...     estimated_tokens=5000
        ... )
    """
    skill_id: str
    required_tools: List[str] = field(default_factory=list)
    role_hints: List[str] = field(default_factory=list)
    estimated_tokens: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "skill_id": self.skill_id,
            "required_tools": self.required_tools,
            "role_hints": self.role_hints,
            "estimated_tokens": self.estimated_tokens
        }


@dataclass
class Constraints:
    """
    Simple representation of policy constraints for resolution.
    
    Defines the boundaries within which skills can operate,
    including allowed tools, budget, and role-specific constraints.
    
    Attributes:
        allowed_tools: List of tool names that are permitted
        budget_remaining: Remaining token budget available
        _role_constraints: Internal storage for role-specific constraints
    
    Example:
        >>> constraints = Constraints(
        ...     allowed_tools=["bash", "python", "git"],
        ...     budget_remaining=10000
        ... )
        >>> constraints.get_role_constraints("developer")
        []
    """
    allowed_tools: List[str] = field(default_factory=list)
    budget_remaining: int = 0
    _role_constraints: Dict[str, List[Constraint]] = field(default_factory=dict)
    
    def get_role_constraints(self, role: str) -> List[Constraint]:
        """
        Get constraints specific to a role.
        
        Args:
            role: The role name to look up constraints for
            
        Returns:
            List of constraints for the given role, empty list if none
        """
        return self._role_constraints.get(role, [])
    
    def add_role_constraint(self, role: str, constraint: Constraint) -> None:
        """
        Add a constraint for a specific role.
        
        Args:
            role: The role name
            constraint: The constraint to add
        """
        if role not in self._role_constraints:
            self._role_constraints[role] = []
        self._role_constraints[role].append(constraint)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "allowed_tools": self.allowed_tools,
            "budget_remaining": self.budget_remaining,
            "role_constraints": {
                role: [getattr(c, 'name', str(c)) for c in constraints]
                for role, constraints in self._role_constraints.items()
            }
        }


# =============================================================================
# Simple Constraint Implementations
# =============================================================================

@dataclass
class ToolConstraint:
    """
    Constraint that restricts which tools can be used.
    
    Attributes:
        name: Constraint name
        description: Human-readable description
        forbidden_tools: List of tools that are forbidden for this role
    """
    name: str
    description: str = ""
    forbidden_tools: List[str] = field(default_factory=list)
    
    def violates(self, skill: Skill) -> bool:
        """Check if the skill uses any forbidden tools."""
        return any(
            tool in self.forbidden_tools
            for tool in skill.required_tools
        )


@dataclass
class BudgetConstraint:
    """
    Constraint that limits budget usage.
    
    Attributes:
        name: Constraint name
        description: Human-readable description
        max_tokens: Maximum tokens allowed for this role
    """
    name: str
    description: str = ""
    max_tokens: int = 1000
    
    def violates(self, skill: Skill) -> bool:
        """Check if the skill exceeds the budget limit."""
        return skill.estimated_tokens > self.max_tokens


# =============================================================================
# Policy Resolver
# =============================================================================

class PolicyResolver:
    """
    Resolves policy conflicts for skills during the EQUIP stage.
    
    The PolicyResolver evaluates skills against policy constraints
    to determine if they can be executed. It handles:
    
    - Tool validation: Checks that required tools are allowed
    - Role-based constraints: Validates role hints against constraints
    - Budget management: Ensures skills don't exceed available budget
    - Security policies: Flags tools marked as unsafe
    
    Resolution Logic:
        1. Check each required tool against allowed_tools list
        2. Validate role hints against role-specific constraints
        3. Verify budget availability
        4. Determine final resolution status based on conflict severities
    
    Example:
        >>> resolver = PolicyResolver()
        >>> skill = Skill(
        ...     skill_id="skill-001",
        ...     required_tools=["bash", "git"],
        ...     role_hints=["developer"],
        ...     estimated_tokens=5000
        ... )
        >>> constraints = Constraints(
        ...     allowed_tools=["bash", "git", "python"],
        ...     budget_remaining=10000
        ... )
        >>> result = resolver.resolve(skill, constraints, ["developer"])
        >>> result.resolution
        <ResolutionStatus.ALLOWED: 'ALLOWED'>
    """
    
    # Tools that are considered unsafe and require special handling
    UNSAFE_TOOLS: frozenset = frozenset({
        "bash", "shell", "exec", "eval", "subprocess"
    })
    
    def __init__(
        self,
        strict_mode: bool = False,
        allow_budget_override: bool = False
    ) -> None:
        """
        Initialize the PolicyResolver.
        
        Args:
            strict_mode: If True, all warnings become errors
            allow_budget_override: If True, budget can be overridden with approval
        """
        self.strict_mode = strict_mode
        self.allow_budget_override = allow_budget_override
        logger.info(
            f"PolicyResolver initialized: strict_mode={strict_mode}, "
            f"allow_budget_override={allow_budget_override}"
        )
    
    def resolve(
        self,
        skill: Skill,
        constraints: Constraints,
        role_hints: List[str]
    ) -> ResolutionResult:
        """
        Resolve policy for a skill against given constraints.
        
        This is the main entry point for policy resolution. It evaluates
        the skill against all relevant constraints and determines whether
        the skill can be executed.
        
        Args:
            skill: The skill to evaluate
            constraints: The policy constraints to check against
            role_hints: Role hints for role-specific constraint evaluation
            
        Returns:
            ResolutionResult containing the resolution status and any conflicts
            
        Example:
            >>> result = resolver.resolve(skill, constraints, ["admin"])
            >>> if result.is_executable():
            ...     print(f"Skill {result.skill_id} can execute")
        """
        logger.info(f"Resolving policy for skill: {skill.skill_id}")
        
        conflicts: List[Conflict] = []
        warnings: List[str] = []
        required_approvals: List[str] = []
        overridden_constraints: List[str] = []
        
        # 1. Check tools against allowed_tools
        tool_conflicts = self.validate_tools(
            skill.required_tools,
            constraints.allowed_tools
        )
        conflicts.extend(tool_conflicts)
        
        # 2. Check for security policy violations (unsafe tools)
        for tool in skill.required_tools:
            if tool in self.UNSAFE_TOOLS:
                conflicts.append(Conflict(
                    type=ConflictType.SECURITY_POLICY_VIOLATION,
                    severity="WARN",
                    details=f"Tool '{tool}' is marked as unsafe and requires caution",
                    skill_id=skill.skill_id
                ))
        
        # 3. Check role_hints vs policy constraints
        for role in role_hints:
            role_constraints = constraints.get_role_constraints(role)
            for constraint in role_constraints:
                if constraint.violates(skill):
                    conflicts.append(Conflict(
                        type=ConflictType.ROLE_POLICY_MISMATCH,
                        severity="WARN",
                        details=f"Role '{role}' constraint '{getattr(constraint, 'name', constraint)}' violated",
                        skill_id=skill.skill_id
                    ))
        
        # 4. Check budget
        budget_conflict = self.check_budget_override(
            skill, constraints.budget_remaining
        )
        if budget_conflict:
            conflicts.append(budget_conflict)
        
        # 5. Check style guide violations (placeholder for future implementation)
        # TODO: Implement style guide validation
        
        # Determine resolution
        has_errors = any(c.severity == "ERROR" for c in conflicts)
        has_warnings = any(c.severity == "WARN" for c in conflicts)
        
        # Apply strict mode if enabled
        if self.strict_mode and has_warnings:
            has_errors = True
        
        # Determine final resolution
        if has_errors:
            resolution = ResolutionStatus.BLOCKED
        elif has_warnings or required_approvals:
            resolution = ResolutionStatus.CONDITIONAL
        else:
            resolution = ResolutionStatus.ALLOWED
        
        # Collect warning messages
        warnings = [
            c.details for c in conflicts if c.severity == "WARN"
        ]
        
        # Log resolution result
        logger.info(
            f"Policy resolution for {skill.skill_id}: {resolution.value} "
            f"(errors={has_errors}, warnings={len(warnings)})"
        )
        
        return ResolutionResult(
            skill_id=skill.skill_id,
            resolution=resolution,
            conflicts=conflicts,
            warnings=warnings,
            required_approvals=required_approvals,
            overridden_constraints=overridden_constraints
        )
    
    def validate_tools(
        self,
        tools: List[str],
        allowed_tools: List[str]
    ) -> List[Conflict]:
        """
        Validate that all required tools are in the allowed list.
        
        Args:
            tools: List of tool names required by a skill
            allowed_tools: List of tool names that are permitted
            
        Returns:
            List of conflicts for any tools not in the allowed list
            
        Example:
            >>> conflicts = resolver.validate_tools(
            ...     ["bash", "python"],
            ...     ["python", "git"]
            ... )
            >>> len(conflicts)
            1
        """
        conflicts: List[Conflict] = []
        allowed_set = set(allowed_tools)
        
        for tool in tools:
            if tool not in allowed_set:
                conflicts.append(Conflict(
                    type=ConflictType.TOOL_NOT_ALLOWED,
                    severity="ERROR",
                    details=f"Tool '{tool}' not in allowed_tools",
                    skill_id=""  # Will be set by caller
                ))
                logger.debug(f"Tool '{tool}' not in allowed_tools")
        
        return conflicts
    
    def check_budget_override(
        self,
        skill: Skill,
        budget: int
    ) -> Optional[Conflict]:
        """
        Check if the skill exceeds the available budget.
        
        Args:
            skill: The skill to check
            budget: Available budget in tokens
            
        Returns:
            Conflict if budget is exceeded, None otherwise
            
        Example:
            >>> conflict = resolver.check_budget_override(skill, 1000)
            >>> if conflict:
            ...     print(f"Budget exceeded: {conflict.details}")
        """
        if skill.estimated_tokens > budget:
            severity = "ERROR"
            
            # If budget override is allowed, downgrade to conditional
            if self.allow_budget_override:
                severity = "WARN"
                logger.warning(
                    f"Budget override allowed for skill {skill.skill_id}: "
                    f"requires {skill.estimated_tokens}, available {budget}"
                )
            
            return Conflict(
                type=ConflictType.BUDGET_EXCEEDED,
                severity=severity,
                details=f"Skill requires {skill.estimated_tokens} tokens, "
                       f"but only {budget} available",
                skill_id=skill.skill_id
            )
        
        return None
    
    def lint_conflicts(
        self,
        skills: List[Skill],
        constraints: Constraints
    ) -> List[Conflict]:
        """
        Lint a batch of skills for potential conflicts.
        
        This method performs a quick check across multiple skills
        to identify potential issues before individual resolution.
        Useful for pre-flight validation during the EQUIP stage.
        
        Args:
            skills: List of skills to lint
            constraints: Policy constraints to check against
            
        Returns:
            List of all conflicts found across all skills
            
        Example:
            >>> conflicts = resolver.lint_conflicts(
            ...     [skill1, skill2, skill3],
            ...     constraints
            ... )
            >>> print(f"Found {len(conflicts)} potential conflicts")
        """
        all_conflicts: List[Conflict] = []
        
        # Track cumulative budget usage
        total_estimated_tokens = 0
        
        for skill in skills:
            # Check tools
            tool_conflicts = self.validate_tools(
                skill.required_tools,
                constraints.allowed_tools
            )
            for conflict in tool_conflicts:
                conflict = Conflict(
                    type=conflict.type,
                    severity=conflict.severity,
                    details=conflict.details,
                    skill_id=skill.skill_id
                )
                all_conflicts.append(conflict)
            
            # Check for unsafe tools
            for tool in skill.required_tools:
                if tool in self.UNSAFE_TOOLS:
                    all_conflicts.append(Conflict(
                        type=ConflictType.SECURITY_POLICY_VIOLATION,
                        severity="WARN",
                        details=f"Skill '{skill.skill_id}' uses unsafe tool '{tool}'",
                        skill_id=skill.skill_id
                    ))
            
            # Accumulate budget
            total_estimated_tokens += skill.estimated_tokens
        
        # Check cumulative budget
        if total_estimated_tokens > constraints.budget_remaining:
            all_conflicts.append(Conflict(
                type=ConflictType.BUDGET_EXCEEDED,
                severity="WARN",  # Warning for batch, might be OK with priority
                details=f"Total estimated tokens ({total_estimated_tokens}) exceeds "
                       f"available budget ({constraints.budget_remaining})",
                skill_id="__batch__"
            ))
        
        logger.info(
            f"Linted {len(skills)} skills, found {len(all_conflicts)} conflicts"
        )
        
        return all_conflicts


# =============================================================================
# Convenience Functions
# =============================================================================

def create_policy_resolver(
    strict_mode: bool = False,
    allow_budget_override: bool = False
) -> PolicyResolver:
    """
    Factory function to create a PolicyResolver instance.
    
    Args:
        strict_mode: If True, all warnings become errors
        allow_budget_override: If True, budget can be overridden with approval
        
    Returns:
        Configured PolicyResolver instance
    """
    return PolicyResolver(
        strict_mode=strict_mode,
        allow_budget_override=allow_budget_override
    )


def resolve_skill_policy(
    skill: Skill,
    constraints: Constraints,
    role_hints: List[str],
    strict_mode: bool = False
) -> ResolutionResult:
    """
    Convenience function to resolve policy for a single skill.
    
    Args:
        skill: The skill to evaluate
        constraints: Policy constraints to check against
        role_hints: Role hints for constraint evaluation
        strict_mode: If True, all warnings become errors
        
    Returns:
        ResolutionResult for the skill
    """
    resolver = PolicyResolver(strict_mode=strict_mode)
    return resolver.resolve(skill, constraints, role_hints)


def lint_skills(
    skills: List[Skill],
    constraints: Constraints
) -> List[Conflict]:
    """
    Convenience function to lint a batch of skills.
    
    Args:
        skills: List of skills to lint
        constraints: Policy constraints to check against
        
    Returns:
        List of conflicts found
    """
    resolver = PolicyResolver()
    return resolver.lint_conflicts(skills, constraints)
