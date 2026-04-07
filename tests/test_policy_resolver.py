"""
Tests for ITEM-POLICY-01: PolicyResolver for EQUIP Stage

This module tests the PolicyResolver implementation for policy conflict
resolution during the EQUIP stage.

Author: TITAN FUSE Team
Version: 1.0.0
"""

import pytest
from unittest.mock import Mock, MagicMock

from src.policy.policy_resolver import (
    PolicyResolver,
    ConflictType,
    Conflict,
    ResolutionStatus,
    ResolutionResult,
    Skill,
    Constraints,
    ToolConstraint,
    BudgetConstraint,
    create_policy_resolver,
    resolve_skill_policy,
    lint_skills,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def resolver():
    """Create a default PolicyResolver for testing."""
    return PolicyResolver()


@pytest.fixture
def strict_resolver():
    """Create a strict mode PolicyResolver for testing."""
    return PolicyResolver(strict_mode=True)


@pytest.fixture
def budget_override_resolver():
    """Create a resolver with budget override allowed."""
    return PolicyResolver(allow_budget_override=True)


@pytest.fixture
def sample_skill():
    """Create a sample skill for testing."""
    return Skill(
        skill_id="skill-001",
        required_tools=["bash", "python", "git"],
        role_hints=["developer"],
        estimated_tokens=5000
    )


@pytest.fixture
def sample_constraints():
    """Create sample constraints for testing."""
    return Constraints(
        allowed_tools=["bash", "python", "git", "docker"],
        budget_remaining=10000
    )


# =============================================================================
# Test ConflictType Enum
# =============================================================================

class TestConflictType:
    """Tests for ConflictType enum."""

    def test_tool_not_allowed_exists(self):
        """Test TOOL_NOT_ALLOWED conflict type exists."""
        assert hasattr(ConflictType, "TOOL_NOT_ALLOWED")
        assert ConflictType.TOOL_NOT_ALLOWED.value == "required_tool not in allowed_tools"

    def test_role_policy_mismatch_exists(self):
        """Test ROLE_POLICY_MISMATCH conflict type exists."""
        assert hasattr(ConflictType, "ROLE_POLICY_MISMATCH")
        assert "role_hints" in ConflictType.ROLE_POLICY_MISMATCH.value

    def test_budget_exceeded_exists(self):
        """Test BUDGET_EXCEEDED conflict type exists."""
        assert hasattr(ConflictType, "BUDGET_EXCEEDED")
        assert "budget" in ConflictType.BUDGET_EXCEEDED.value.lower()

    def test_style_guide_violation_exists(self):
        """Test STYLE_GUIDE_VIOLATION conflict type exists."""
        assert hasattr(ConflictType, "STYLE_GUIDE_VIOLATION")

    def test_security_policy_violation_exists(self):
        """Test SECURITY_POLICY_VIOLATION conflict type exists."""
        assert hasattr(ConflictType, "SECURITY_POLICY_VIOLATION")

    def test_all_conflict_types_are_strings(self):
        """Test all conflict type values are strings."""
        for conflict_type in ConflictType:
            assert isinstance(conflict_type.value, str)


# =============================================================================
# Test Conflict
# =============================================================================

class TestConflict:
    """Tests for Conflict dataclass."""

    def test_create_conflict(self):
        """Test creating a Conflict instance."""
        conflict = Conflict(
            type=ConflictType.TOOL_NOT_ALLOWED,
            severity="ERROR",
            details="Tool 'bash' not in allowed_tools",
            skill_id="skill-001"
        )
        assert conflict.type == ConflictType.TOOL_NOT_ALLOWED
        assert conflict.severity == "ERROR"
        assert conflict.skill_id == "skill-001"

    def test_conflict_invalid_severity(self):
        """Test that invalid severity raises ValueError."""
        with pytest.raises(ValueError):
            Conflict(
                type=ConflictType.TOOL_NOT_ALLOWED,
                severity="CRITICAL",  # Invalid - should be ERROR or WARN
                details="Test",
                skill_id="skill-001"
            )

    def test_conflict_warn_severity(self):
        """Test creating a warning conflict."""
        conflict = Conflict(
            type=ConflictType.SECURITY_POLICY_VIOLATION,
            severity="WARN",
            details="Tool marked as unsafe",
            skill_id="skill-001"
        )
        assert conflict.severity == "WARN"

    def test_to_dict(self):
        """Test Conflict serialization to dictionary."""
        conflict = Conflict(
            type=ConflictType.BUDGET_EXCEEDED,
            severity="ERROR",
            details="Budget exceeded",
            skill_id="skill-001"
        )
        d = conflict.to_dict()
        assert d["type"] == ConflictType.BUDGET_EXCEEDED.value
        assert d["severity"] == "ERROR"
        assert d["skill_id"] == "skill-001"


# =============================================================================
# Test ResolutionStatus Enum
# =============================================================================

class TestResolutionStatus:
    """Tests for ResolutionStatus enum."""

    def test_allowed_status(self):
        """Test ALLOWED status exists."""
        assert hasattr(ResolutionStatus, "ALLOWED")
        assert ResolutionStatus.ALLOWED.value == "ALLOWED"

    def test_blocked_status(self):
        """Test BLOCKED status exists."""
        assert hasattr(ResolutionStatus, "BLOCKED")
        assert ResolutionStatus.BLOCKED.value == "BLOCKED"

    def test_conditional_status(self):
        """Test CONDITIONAL status exists."""
        assert hasattr(ResolutionStatus, "CONDITIONAL")
        assert ResolutionStatus.CONDITIONAL.value == "CONDITIONAL"


# =============================================================================
# Test ResolutionResult
# =============================================================================

class TestResolutionResult:
    """Tests for ResolutionResult dataclass."""

    def test_create_allowed_result(self):
        """Test creating an ALLOWED resolution result."""
        result = ResolutionResult(
            skill_id="skill-001",
            resolution=ResolutionStatus.ALLOWED,
            conflicts=[],
            warnings=[]
        )
        assert result.resolution == ResolutionStatus.ALLOWED
        assert result.is_executable() is True

    def test_create_blocked_result(self):
        """Test creating a BLOCKED resolution result."""
        result = ResolutionResult(
            skill_id="skill-001",
            resolution=ResolutionStatus.BLOCKED,
            conflicts=[Conflict(
                type=ConflictType.TOOL_NOT_ALLOWED,
                severity="ERROR",
                details="Tool not allowed",
                skill_id="skill-001"
            )],
            warnings=[]
        )
        assert result.resolution == ResolutionStatus.BLOCKED
        assert result.is_executable() is False

    def test_create_conditional_result(self):
        """Test creating a CONDITIONAL resolution result."""
        result = ResolutionResult(
            skill_id="skill-001",
            resolution=ResolutionStatus.CONDITIONAL,
            conflicts=[],
            warnings=["Warning message"],
            required_approvals=["admin"]
        )
        assert result.resolution == ResolutionStatus.CONDITIONAL
        assert result.is_executable() is True  # CONDITIONAL is executable

    def test_to_dict(self):
        """Test ResolutionResult serialization."""
        result = ResolutionResult(
            skill_id="skill-001",
            resolution=ResolutionStatus.ALLOWED,
            conflicts=[],
            warnings=["Test warning"]
        )
        d = result.to_dict()
        assert d["skill_id"] == "skill-001"
        assert d["resolution"] == "ALLOWED"
        assert d["is_executable"] is True


# =============================================================================
# Test Skill
# =============================================================================

class TestSkillDataclass:
    """Tests for Skill dataclass in policy module."""

    def test_create_skill(self):
        """Test creating a Skill instance."""
        skill = Skill(
            skill_id="test-skill",
            required_tools=["bash"],
            role_hints=["developer"],
            estimated_tokens=1000
        )
        assert skill.skill_id == "test-skill"
        assert "bash" in skill.required_tools

    def test_skill_defaults(self):
        """Test Skill default values."""
        skill = Skill(skill_id="test-skill")
        assert skill.required_tools == []
        assert skill.role_hints == []
        assert skill.estimated_tokens == 0

    def test_to_dict(self):
        """Test Skill serialization."""
        skill = Skill(
            skill_id="test-skill",
            required_tools=["python"],
            estimated_tokens=500
        )
        d = skill.to_dict()
        assert d["skill_id"] == "test-skill"
        assert d["required_tools"] == ["python"]
        assert d["estimated_tokens"] == 500


# =============================================================================
# Test Constraints
# =============================================================================

class TestConstraints:
    """Tests for Constraints dataclass."""

    def test_create_constraints(self):
        """Test creating a Constraints instance."""
        constraints = Constraints(
            allowed_tools=["bash", "python"],
            budget_remaining=5000
        )
        assert "bash" in constraints.allowed_tools
        assert constraints.budget_remaining == 5000

    def test_get_role_constraints_empty(self):
        """Test getting role constraints when none exist."""
        constraints = Constraints()
        assert constraints.get_role_constraints("admin") == []

    def test_add_role_constraint(self):
        """Test adding a role constraint."""
        constraints = Constraints()
        constraint = ToolConstraint(
            name="no_shell",
            forbidden_tools=["bash", "shell"]
        )
        constraints.add_role_constraint("guest", constraint)
        
        result = constraints.get_role_constraints("guest")
        assert len(result) == 1

    def test_to_dict(self):
        """Test Constraints serialization."""
        constraints = Constraints(
            allowed_tools=["python"],
            budget_remaining=1000
        )
        d = constraints.to_dict()
        assert d["allowed_tools"] == ["python"]
        assert d["budget_remaining"] == 1000


# =============================================================================
# Test ToolConstraint
# =============================================================================

class TestToolConstraint:
    """Tests for ToolConstraint dataclass."""

    def test_tool_constraint_violates(self):
        """Test ToolConstraint violation detection."""
        constraint = ToolConstraint(
            name="no_shell",
            forbidden_tools=["bash", "shell", "exec"]
        )
        
        skill = Skill(
            skill_id="skill-001",
            required_tools=["bash", "python"]
        )
        
        assert constraint.violates(skill) is True

    def test_tool_constraint_no_violation(self):
        """Test ToolConstraint with no violation."""
        constraint = ToolConstraint(
            name="no_shell",
            forbidden_tools=["bash", "shell"]
        )
        
        skill = Skill(
            skill_id="skill-001",
            required_tools=["python", "git"]
        )
        
        assert constraint.violates(skill) is False


# =============================================================================
# Test BudgetConstraint
# =============================================================================

class TestBudgetConstraint:
    """Tests for BudgetConstraint dataclass."""

    def test_budget_constraint_violates(self):
        """Test BudgetConstraint violation detection."""
        constraint = BudgetConstraint(
            name="low_budget_role",
            max_tokens=1000
        )
        
        skill = Skill(
            skill_id="skill-001",
            estimated_tokens=5000
        )
        
        assert constraint.violates(skill) is True

    def test_budget_constraint_no_violation(self):
        """Test BudgetConstraint with no violation."""
        constraint = BudgetConstraint(
            name="low_budget_role",
            max_tokens=10000
        )
        
        skill = Skill(
            skill_id="skill-001",
            estimated_tokens=5000
        )
        
        assert constraint.violates(skill) is False


# =============================================================================
# Test PolicyResolver.resolve()
# =============================================================================

class TestPolicyResolverResolve:
    """Tests for PolicyResolver.resolve() method."""

    def test_resolve_allowed_case(self, resolver, sample_skill, sample_constraints):
        """Test resolution with all valid conditions (ALLOWED)."""
        result = resolver.resolve(
            skill=sample_skill,
            constraints=sample_constraints,
            role_hints=["developer"]
        )
        
        # Should be CONDITIONAL because bash is in UNSAFE_TOOLS
        assert result.resolution in (ResolutionStatus.ALLOWED, ResolutionStatus.CONDITIONAL)
        assert result.skill_id == "skill-001"

    def test_resolve_blocked_tool_not_allowed(self, resolver, sample_constraints):
        """Test resolution when tool is not allowed (BLOCKED)."""
        skill = Skill(
            skill_id="skill-002",
            required_tools=["bash", "dangerous_tool"],  # dangerous_tool not in allowed
            role_hints=["developer"],
            estimated_tokens=1000
        )
        
        result = resolver.resolve(
            skill=skill,
            constraints=sample_constraints,
            role_hints=["developer"]
        )
        
        assert result.resolution == ResolutionStatus.BLOCKED
        assert any(c.type == ConflictType.TOOL_NOT_ALLOWED for c in result.conflicts)

    def test_resolve_blocked_budget_exceeded(self, resolver, sample_skill):
        """Test resolution when budget is exceeded (BLOCKED)."""
        constraints = Constraints(
            allowed_tools=["bash", "python", "git"],
            budget_remaining=1000  # Less than skill's 5000
        )
        
        result = resolver.resolve(
            skill=sample_skill,
            constraints=constraints,
            role_hints=["developer"]
        )
        
        assert result.resolution == ResolutionStatus.BLOCKED
        assert any(c.type == ConflictType.BUDGET_EXCEEDED for c in result.conflicts)

    def test_resolve_conditional_warnings_only(self, resolver, sample_constraints):
        """Test resolution with only warnings (CONDITIONAL)."""
        skill = Skill(
            skill_id="skill-003",
            required_tools=["bash"],  # bash is in UNSAFE_TOOLS
            role_hints=["developer"],
            estimated_tokens=1000
        )
        
        result = resolver.resolve(
            skill=skill,
            constraints=sample_constraints,
            role_hints=["developer"]
        )
        
        # Should be CONDITIONAL because bash is unsafe (WARN)
        assert result.resolution == ResolutionStatus.CONDITIONAL
        assert len(result.warnings) > 0

    def test_resolve_with_role_constraints(self, resolver):
        """Test resolution with role-specific constraints."""
        # Create constraint that forbids bash for guest role
        constraint = ToolConstraint(
            name="guest_no_shell",
            forbidden_tools=["bash"]
        )
        
        constraints = Constraints(
            allowed_tools=["bash", "python"],
            budget_remaining=10000
        )
        constraints.add_role_constraint("guest", constraint)
        
        skill = Skill(
            skill_id="skill-004",
            required_tools=["bash"],
            role_hints=["guest"],
            estimated_tokens=1000
        )
        
        result = resolver.resolve(
            skill=skill,
            constraints=constraints,
            role_hints=["guest"]
        )
        
        # Should have ROLE_POLICY_MISMATCH conflict
        assert any(c.type == ConflictType.ROLE_POLICY_MISMATCH for c in result.conflicts)

    def test_resolve_strict_mode(self, strict_resolver, sample_constraints):
        """Test that strict mode treats warnings as errors."""
        skill = Skill(
            skill_id="skill-005",
            required_tools=["bash"],  # Unsafe tool - generates WARN
            role_hints=["developer"],
            estimated_tokens=1000
        )
        
        result = strict_resolver.resolve(
            skill=skill,
            constraints=sample_constraints,
            role_hints=["developer"]
        )
        
        # In strict mode, WARN becomes ERROR -> BLOCKED
        assert result.resolution == ResolutionStatus.BLOCKED

    def test_resolve_budget_override(self, budget_override_resolver, sample_skill):
        """Test that budget override downgrades severity."""
        constraints = Constraints(
            allowed_tools=["bash", "python", "git"],
            budget_remaining=100  # Much less than skill's 5000
        )
        
        result = budget_override_resolver.resolve(
            skill=sample_skill,
            constraints=constraints,
            role_hints=["developer"]
        )
        
        # Budget conflict should be WARN, not ERROR
        budget_conflicts = [c for c in result.conflicts if c.type == ConflictType.BUDGET_EXCEEDED]
        if budget_conflicts:
            assert budget_conflicts[0].severity == "WARN"


# =============================================================================
# Test PolicyResolver.validate_tools()
# =============================================================================

class TestPolicyResolverValidateTools:
    """Tests for PolicyResolver.validate_tools() method."""

    def test_validate_tools_all_allowed(self, resolver):
        """Test validation when all tools are allowed."""
        conflicts = resolver.validate_tools(
            tools=["python", "git"],
            allowed_tools=["bash", "python", "git", "docker"]
        )
        assert len(conflicts) == 0

    def test_validate_tools_one_not_allowed(self, resolver):
        """Test validation when one tool is not allowed."""
        conflicts = resolver.validate_tools(
            tools=["python", "dangerous_tool"],
            allowed_tools=["bash", "python", "git"]
        )
        assert len(conflicts) == 1
        assert conflicts[0].type == ConflictType.TOOL_NOT_ALLOWED

    def test_validate_tools_multiple_not_allowed(self, resolver):
        """Test validation when multiple tools are not allowed."""
        conflicts = resolver.validate_tools(
            tools=["tool1", "tool2", "tool3"],
            allowed_tools=["tool1"]
        )
        assert len(conflicts) == 2

    def test_validate_tools_empty(self, resolver):
        """Test validation with empty tools list."""
        conflicts = resolver.validate_tools(
            tools=[],
            allowed_tools=["bash", "python"]
        )
        assert len(conflicts) == 0


# =============================================================================
# Test PolicyResolver.lint_conflicts()
# =============================================================================

class TestPolicyResolverLintConflicts:
    """Tests for PolicyResolver.lint_conflicts() method."""

    def test_lint_conflicts_no_issues(self, resolver, sample_constraints):
        """Test linting skills with no conflicts."""
        skills = [
            Skill(skill_id="s1", required_tools=["python"], estimated_tokens=1000),
            Skill(skill_id="s2", required_tools=["git"], estimated_tokens=1000),
        ]
        
        conflicts = resolver.lint_conflicts(skills, sample_constraints)
        
        # Should only have batch budget warning (2000 < 10000, so no issue)
        assert len(conflicts) == 0

    def test_lint_conflicts_with_tool_issues(self, resolver, sample_constraints):
        """Test linting skills with tool conflicts."""
        skills = [
            Skill(skill_id="s1", required_tools=["python"], estimated_tokens=1000),
            Skill(skill_id="s2", required_tools=["forbidden_tool"], estimated_tokens=1000),
        ]
        
        conflicts = resolver.lint_conflicts(skills, sample_constraints)
        
        assert len(conflicts) > 0
        assert any(c.type == ConflictType.TOOL_NOT_ALLOWED for c in conflicts)

    def test_lint_conflicts_with_unsafe_tools(self, resolver, sample_constraints):
        """Test linting detects unsafe tools."""
        skills = [
            Skill(skill_id="s1", required_tools=["bash"], estimated_tokens=1000),
        ]
        
        conflicts = resolver.lint_conflicts(skills, sample_constraints)
        
        assert any(c.type == ConflictType.SECURITY_POLICY_VIOLATION for c in conflicts)

    def test_lint_conflicts_cumulative_budget(self, resolver):
        """Test linting detects cumulative budget exceedance."""
        constraints = Constraints(
            allowed_tools=["bash", "python", "git"],
            budget_remaining=1500  # Total skills need 3000
        )
        
        skills = [
            Skill(skill_id="s1", required_tools=["python"], estimated_tokens=1000),
            Skill(skill_id="s2", required_tools=["git"], estimated_tokens=1000),
            Skill(skill_id="s3", required_tools=["bash"], estimated_tokens=1000),
        ]
        
        conflicts = resolver.lint_conflicts(skills, constraints)
        
        # Should have batch budget warning
        assert any(
            c.type == ConflictType.BUDGET_EXCEEDED and c.skill_id == "__batch__"
            for c in conflicts
        )


# =============================================================================
# Test Convenience Functions
# =============================================================================

class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_create_policy_resolver(self):
        """Test create_policy_resolver factory function."""
        resolver = create_policy_resolver(strict_mode=True)
        assert resolver.strict_mode is True

    def test_resolve_skill_policy(self, sample_skill, sample_constraints):
        """Test resolve_skill_policy convenience function."""
        result = resolve_skill_policy(
            skill=sample_skill,
            constraints=sample_constraints,
            role_hints=["developer"]
        )
        assert result.skill_id == "skill-001"

    def test_lint_skills(self, sample_constraints):
        """Test lint_skills convenience function."""
        skills = [
            Skill(skill_id="s1", required_tools=["python"]),
        ]
        
        conflicts = lint_skills(skills, sample_constraints)
        assert isinstance(conflicts, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
