"""
Catalog Validator for TITAN Protocol Skill Library.

ITEM-SKILL-01: Catalog validation with coverage reporting.

This module provides validation utilities for skill catalogs:
- CatalogValidator: Schema and coverage validation
- CoverageReport: Task type coverage metrics
- ValidationError: Validation error representation

Author: TITAN FUSE Team
Version: 3.5.0
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Set
import re


@dataclass
class ValidationError:
    """
    Represents a validation error found during catalog validation.

    Attributes:
        path: Path to the error location in the catalog
        message: Human-readable error message
        severity: Error severity ('error', 'warning', 'info')
        skill_id: Optional skill ID where the error occurred
    """
    path: str
    message: str
    severity: str = "error"
    skill_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "path": self.path,
            "message": self.message,
            "severity": self.severity,
            "skill_id": self.skill_id
        }

    def __str__(self) -> str:
        """String representation."""
        location = f"skill '{self.skill_id}'" if self.skill_id else self.path
        return f"[{self.severity.upper()}] {location}: {self.message}"


@dataclass
class ValidationResult:
    """
    Result of catalog validation.

    Attributes:
        is_valid: Whether the catalog passed all required validations
        errors: List of validation errors
        warnings: List of validation warnings
        coverage_report: Optional coverage report for task types
    """
    is_valid: bool
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)
    coverage_report: Optional['CoverageReport'] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "is_valid": self.is_valid,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
            "coverage_report": self.coverage_report.to_dict() if self.coverage_report else None
        }

    def add_error(self, path: str, message: str, skill_id: str = None) -> None:
        """Add an error to the result."""
        self.errors.append(ValidationError(path, message, "error", skill_id))
        self.is_valid = False

    def add_warning(self, path: str, message: str, skill_id: str = None) -> None:
        """Add a warning to the result."""
        self.warnings.append(ValidationError(path, message, "warning", skill_id))


@dataclass
class CoverageReport:
    """
    Report on task type coverage by skills.

    Attributes:
        covered_task_types: Task types that have at least one skill
        uncovered_task_types: Task types without any skills
        coverage_percentage: Percentage of task types covered (0-100)
    """
    covered_task_types: List[str] = field(default_factory=list)
    uncovered_task_types: List[str] = field(default_factory=list)
    coverage_percentage: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "covered_task_types": self.covered_task_types,
            "uncovered_task_types": self.uncovered_task_types,
            "coverage_percentage": self.coverage_percentage
        }

    def __str__(self) -> str:
        """String representation."""
        return (
            f"Coverage: {self.coverage_percentage:.1f}% "
            f"({len(self.covered_task_types)} covered, "
            f"{len(self.uncovered_task_types)} uncovered)"
        )


class CatalogValidator:
    """
    Validates skill catalogs for schema compliance and coverage.

    The CatalogValidator performs multiple validation checks:
    1. Schema validation: Ensures required fields are present
    2. Coverage validation: Checks task type coverage
    3. Synergy detection: Identifies skills with cross-task applicability

    Example:
        >>> validator = CatalogValidator()
        >>> errors = validator.validate_schema(catalog_data)
        >>> coverage = validator.check_applicable_to_coverage(skills, task_types)
        >>> synergy_issues = validator.detect_missing_synergy(skills)
    """

    # Required fields for a valid skill definition
    REQUIRED_SKILL_FIELDS = {"skill_id", "description", "applicable_to"}

    # Required fields for a valid pattern definition
    REQUIRED_PATTERN_FIELDS = {"pattern_name"}

    # Valid skill ID pattern (alphanumeric, underscores, hyphens)
    SKILL_ID_PATTERN = re.compile(r'^[a-zA-Z][a-zA-Z0-9_-]*$')

    def __init__(self, strict_mode: bool = False):
        """
        Initialize the CatalogValidator.

        Args:
            strict_mode: If True, warnings are treated as errors
        """
        self.strict_mode = strict_mode

    def validate_schema(self, catalog: Dict[str, Any]) -> List[ValidationError]:
        """
        Validate catalog schema structure.

        Checks:
        - Version field presence and format
        - Skills list presence and structure
        - Required fields in each skill
        - Pattern structure in reusable_patterns
        - Role hints and tool references validity

        Args:
            catalog: The catalog dictionary to validate

        Returns:
            List of ValidationError objects found
        """
        errors: List[ValidationError] = []

        # Check top-level fields
        if "version" not in catalog:
            errors.append(ValidationError(
                path="catalog",
                message="Missing required field 'version'"
            ))

        if "skills" not in catalog:
            errors.append(ValidationError(
                path="catalog",
                message="Missing required field 'skills'"
            ))
            return errors  # Can't continue without skills list

        if not isinstance(catalog["skills"], list):
            errors.append(ValidationError(
                path="catalog.skills",
                message="'skills' must be a list"
            ))
            return errors

        # Validate each skill
        skill_ids: Set[str] = set()

        for idx, skill_data in enumerate(catalog["skills"]):
            skill_path = f"catalog.skills[{idx}]"

            if not isinstance(skill_data, dict):
                errors.append(ValidationError(
                    path=skill_path,
                    message="Skill entry must be a dictionary"
                ))
                continue

            # Check required fields
            for field_name in self.REQUIRED_SKILL_FIELDS:
                if field_name not in skill_data:
                    errors.append(ValidationError(
                        path=f"{skill_path}.{field_name}",
                        message=f"Missing required field '{field_name}'"
                    ))

            # Validate skill_id
            skill_id = skill_data.get("skill_id")
            if skill_id:
                # Check format
                if not self.SKILL_ID_PATTERN.match(skill_id):
                    errors.append(ValidationError(
                        path=f"{skill_path}.skill_id",
                        message=f"Invalid skill_id format: '{skill_id}'",
                        skill_id=skill_id
                    ))

                # Check uniqueness
                if skill_id in skill_ids:
                    errors.append(ValidationError(
                        path=f"{skill_path}.skill_id",
                        message=f"Duplicate skill_id: '{skill_id}'",
                        skill_id=skill_id
                    ))
                skill_ids.add(skill_id)

            # Validate applicable_to
            applicable_to = skill_data.get("applicable_to", [])
            if not isinstance(applicable_to, list):
                errors.append(ValidationError(
                    path=f"{skill_path}.applicable_to",
                    message="'applicable_to' must be a list",
                    skill_id=skill_id
                ))
            elif len(applicable_to) == 0:
                errors.append(ValidationError(
                    path=f"{skill_path}.applicable_to",
                    message="'applicable_to' cannot be empty",
                    skill_id=skill_id
                ))

            # Validate role_hints
            role_hints = skill_data.get("role_hints", [])
            if not isinstance(role_hints, list):
                errors.append(ValidationError(
                    path=f"{skill_path}.role_hints",
                    message="'role_hints' must be a list",
                    skill_id=skill_id
                ))

            # Validate required_tools
            required_tools = skill_data.get("required_tools", [])
            if not isinstance(required_tools, list):
                errors.append(ValidationError(
                    path=f"{skill_path}.required_tools",
                    message="'required_tools' must be a list",
                    skill_id=skill_id
                ))

            # Validate validation_chain
            validation_chain = skill_data.get("validation_chain", [])
            if not isinstance(validation_chain, list):
                errors.append(ValidationError(
                    path=f"{skill_path}.validation_chain",
                    message="'validation_chain' must be a list",
                    skill_id=skill_id
                ))

            # Validate reusable_patterns
            patterns = skill_data.get("reusable_patterns", [])
            if not isinstance(patterns, list):
                errors.append(ValidationError(
                    path=f"{skill_path}.reusable_patterns",
                    message="'reusable_patterns' must be a list",
                    skill_id=skill_id
                ))
            else:
                # Validate each pattern
                for pidx, pattern in enumerate(patterns):
                    pattern_path = f"{skill_path}.reusable_patterns[{pidx}]"

                    if not isinstance(pattern, dict):
                        errors.append(ValidationError(
                            path=pattern_path,
                            message="Pattern must be a dictionary",
                            skill_id=skill_id
                        ))
                        continue

                    for field_name in self.REQUIRED_PATTERN_FIELDS:
                        if field_name not in pattern:
                            errors.append(ValidationError(
                                path=f"{pattern_path}.{field_name}",
                                message=f"Missing required field '{field_name}' in pattern",
                                skill_id=skill_id
                            ))

                    # Validate validation_chain in pattern
                    pattern_chain = pattern.get("validation_chain", [])
                    if not isinstance(pattern_chain, list):
                        errors.append(ValidationError(
                            path=f"{pattern_path}.validation_chain",
                            message="Pattern 'validation_chain' must be a list",
                            skill_id=skill_id
                        ))

        return errors

    def check_applicable_to_coverage(
        self,
        skills: List[Any],
        task_types: List[str]
    ) -> CoverageReport:
        """
        Check which task types are covered by skills.

        A task type is covered if at least one skill's applicable_to
        list contains that task type (exact match or partial match).

        Args:
            skills: List of Skill objects to check
            task_types: List of task types to check coverage for

        Returns:
            CoverageReport with coverage metrics
        """
        if not task_types:
            return CoverageReport(
                covered_task_types=[],
                uncovered_task_types=[],
                coverage_percentage=100.0
            )

        covered: List[str] = []
        uncovered: List[str] = []

        for task_type in task_types:
            task_type_upper = task_type.upper()
            is_covered = False

            for skill in skills:
                for applicable in skill.applicable_to:
                    applicable_upper = applicable.upper()
                    # Check exact or partial match
                    if (task_type_upper == applicable_upper or
                        task_type_upper in applicable_upper or
                        applicable_upper in task_type_upper):
                        is_covered = True
                        break
                if is_covered:
                    break

            if is_covered:
                covered.append(task_type)
            else:
                uncovered.append(task_type)

        # Calculate coverage percentage
        coverage_pct = (len(covered) / len(task_types) * 100) if task_types else 100.0

        return CoverageReport(
            covered_task_types=covered,
            uncovered_task_types=uncovered,
            coverage_percentage=round(coverage_pct, 2)
        )

    def detect_missing_synergy(self, skills: List[Any]) -> List[str]:
        """
        Detect skills that might benefit from synergy but lack it.

        Skills with applicable_to < 2 are considered "single-use" and
        returned in this list. These skills might benefit from being
        extended to support additional task types.

        Note: This returns skills with NO synergy (applicable_to < 2),
        which could indicate missing opportunities for reuse.

        Args:
            skills: List of Skill objects to check

        Returns:
            List of skill IDs that have no synergy (single task type)
        """
        no_synergy_skills: List[str] = []

        for skill in skills:
            if len(skill.applicable_to) < 2:
                no_synergy_skills.append(skill.skill_id)

        return no_synergy_skills

    def validate_catalog(
        self,
        catalog: Dict[str, Any],
        task_types: List[str] = None
    ) -> ValidationResult:
        """
        Perform full catalog validation.

        Combines schema validation, coverage checking, and synergy
        detection into a single comprehensive result.

        Args:
            catalog: The catalog dictionary to validate
            task_types: Optional list of task types to check coverage

        Returns:
            ValidationResult with all validation findings
        """
        result = ValidationResult(is_valid=True)

        # Schema validation
        schema_errors = self.validate_schema(catalog)
        for error in schema_errors:
            if error.severity == "error":
                result.add_error(error.path, error.message, error.skill_id)
            else:
                result.add_warning(error.path, error.message, error.skill_id)

        # If schema is invalid, stop here
        if not result.is_valid:
            return result

        # Import Skill to parse catalog skills
        from .skill import Skill

        # Parse skills for coverage check
        skills: List[Skill] = []
        for skill_data in catalog.get("skills", []):
            try:
                skills.append(Skill.from_dict(skill_data))
            except Exception:
                pass  # Skip invalid skills (already caught by schema validation)

        # Coverage validation if task_types provided
        if task_types:
            result.coverage_report = self.check_applicable_to_coverage(
                skills, task_types
            )

            # Add warnings for uncovered task types
            if result.coverage_report.uncovered_task_types:
                for task_type in result.coverage_report.uncovered_task_types:
                    result.add_warning(
                        "coverage",
                        f"No skill covers task type: {task_type}"
                    )

        # Synergy check
        no_synergy = self.detect_missing_synergy(skills)
        for skill_id in no_synergy:
            result.add_warning(
                f"skills.{skill_id}",
                f"Skill '{skill_id}' has no synergy (only one task type)",
                skill_id=skill_id
            )

        return result


def create_validator(strict_mode: bool = False) -> CatalogValidator:
    """
    Factory function to create a CatalogValidator.

    Args:
        strict_mode: If True, warnings are treated as errors

    Returns:
        CatalogValidator instance
    """
    return CatalogValidator(strict_mode=strict_mode)
