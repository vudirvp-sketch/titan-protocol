"""
Skill Library for TITAN Protocol.

ITEM-SKILL-01: SkillLibrary with catalog management.

This module provides the SkillLibrary class which manages skill
catalogs with selection, registration, and synergy tracking.

Selection Priority:
    1. Exact task_type match + role match
    2. Exact task_type match
    3. Partial task_type match + role match
    4. Partial task_type match

Author: TITAN FUSE Team
Version: 3.5.0
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, TYPE_CHECKING
import yaml

from .skill import Skill, ReusablePattern
from .catalog_validator import (
    CatalogValidator,
    ValidationResult,
    CoverageReport
)

if TYPE_CHECKING:
    from ..events.event_bus import EventBus


@dataclass
class SynergyRecord:
    """
    Records synergy usage for a skill.

    Attributes:
        skill_id: The skill being tracked
        task_types: Task types where this skill was used
        use_count: Total number of times skill was selected
        last_used: Timestamp of last use
    """
    skill_id: str
    task_types: List[str] = field(default_factory=list)
    use_count: int = 0
    last_used: Optional[str] = None

    def record_use(self, task_type: str) -> None:
        """Record a usage of this skill for a task type."""
        if task_type not in self.task_types:
            self.task_types.append(task_type)
        self.use_count += 1
        self.last_used = datetime.utcnow().isoformat() + "Z"


class SkillLibrary:
    """
    Manages a catalog of skills with selection and tracking.

    The SkillLibrary provides:
    - Catalog loading from YAML files
    - Skill selection by task type and role hints
    - Skill registration and updates
    - Pattern lookup across skills
    - Synergy tracking for cross-task skills
    - Catalog validation

    Events Emitted:
        - PATTERN_REUSED: When a skill with applicable_to >= 2 is selected

    Example:
        >>> from src.events import EventBus
        >>> bus = EventBus()
        >>> config = {"catalog_path": "skills/catalog.yaml"}
        >>> library = SkillLibrary(config, bus)
        >>> skills = library.select_skills("AUDIT_CODE", ["architect"])
        >>> for skill in skills:
        ...     print(skill.skill_id)
    """

    def __init__(self, config: Dict[str, Any], event_bus: 'EventBus' = None):
        """
        Initialize the SkillLibrary.

        Args:
            config: Configuration dictionary with optional keys:
                - catalog_path: Path to the catalog YAML file
                - catalog_paths: List of catalog paths to load
                - strict_validation: If True, fail on validation warnings
            event_bus: Optional EventBus for emitting events
        """
        self.config = config
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

        # Internal storage
        self._skills: Dict[str, Skill] = {}
        self._pattern_index: Dict[str, List[str]] = {}  # pattern_name -> skill_ids
        self._synergy_records: Dict[str, SynergyRecord] = {}
        self._validator = CatalogValidator(
            strict_mode=config.get("strict_validation", False)
        )

        # Load catalogs from config
        catalog_path = config.get("catalog_path")
        catalog_paths = config.get("catalog_paths", [])

        if catalog_path:
            catalog_paths = [catalog_path] + catalog_paths

        for path in catalog_paths:
            try:
                self.load_catalog(path)
            except Exception as e:
                self._logger.warning(f"Failed to load catalog {path}: {e}")

    def load_catalog(self, path: str) -> int:
        """
        Load skills from a YAML catalog file.

        Args:
            path: Path to the catalog YAML file

        Returns:
            Number of skills loaded

        Raises:
            FileNotFoundError: If the catalog file doesn't exist
            yaml.YAMLError: If the YAML is malformed
            ValueError: If the catalog fails validation
        """
        catalog_path = Path(path)

        if not catalog_path.exists():
            raise FileNotFoundError(f"Catalog file not found: {path}")

        with open(catalog_path, 'r', encoding='utf-8') as f:
            catalog_data = yaml.safe_load(f)

        if not catalog_data:
            raise ValueError(f"Empty catalog file: {path}")

        # Validate the catalog
        result = self._validator.validate_catalog(catalog_data)
        if not result.is_valid:
            errors = [str(e) for e in result.errors]
            raise ValueError(f"Catalog validation failed: {'; '.join(errors)}")

        # Log warnings
        for warning in result.warnings:
            self._logger.warning(f"Catalog warning: {warning}")

        # Load skills
        skills_loaded = 0
        skills_data = catalog_data.get("skills", [])

        for skill_data in skills_data:
            try:
                skill = Skill.from_dict(skill_data)
                self._skills[skill.skill_id] = skill

                # Index patterns
                for pattern in skill.reusable_patterns:
                    if pattern.pattern_name not in self._pattern_index:
                        self._pattern_index[pattern.pattern_name] = []
                    self._pattern_index[pattern.pattern_name].append(skill.skill_id)

                skills_loaded += 1
                self._logger.debug(f"Loaded skill: {skill.skill_id}")

            except Exception as e:
                self._logger.error(f"Failed to load skill: {e}")

        self._logger.info(f"Loaded {skills_loaded} skills from {path}")
        return skills_loaded

    def get_skill(self, skill_id: str) -> Optional[Skill]:
        """
        Get a skill by its ID.

        Args:
            skill_id: The skill ID to look up

        Returns:
            Skill if found, None otherwise
        """
        return self._skills.get(skill_id)

    def select_skills(
        self,
        task_type: str,
        role_hints: List[str] = None
    ) -> List[Skill]:
        """
        Select skills matching a task type and optional role hints.

        Selection Priority:
            1. Exact task_type match + role match
            2. Exact task_type match
            3. Partial task_type match + role match
            4. Partial task_type match

        Args:
            task_type: The task type to match
            role_hints: Optional list of role hints to match

        Returns:
            List of matching skills ordered by priority
        """
        if role_hints is None:
            role_hints = []

        task_type_upper = task_type.upper()
        role_hints_lower = [r.lower() for r in role_hints]

        # Categorize matches
        exact_with_role: List[Skill] = []
        exact_no_role: List[Skill] = []
        partial_with_role: List[Skill] = []
        partial_no_role: List[Skill] = []

        for skill in self._skills.values():
            # Check task type match
            exact_match = False
            partial_match = False

            for applicable in skill.applicable_to:
                applicable_upper = applicable.upper()
                if applicable_upper == task_type_upper:
                    exact_match = True
                    break
                elif (task_type_upper in applicable_upper or
                      applicable_upper in task_type_upper):
                    partial_match = True

            if not exact_match and not partial_match:
                continue

            # Check role match
            role_match = False
            if role_hints:
                for hint_lower in role_hints_lower:
                    for skill_hint in skill.role_hints:
                        skill_hint_lower = skill_hint.lower()
                        if (hint_lower in skill_hint_lower or
                            skill_hint_lower in hint_lower):
                            role_match = True
                            break
                    if role_match:
                        break

            # Categorize by priority
            if exact_match and role_match:
                exact_with_role.append(skill)
            elif exact_match:
                exact_no_role.append(skill)
            elif partial_match and role_match:
                partial_with_role.append(skill)
            elif partial_match:
                partial_no_role.append(skill)

        # Combine in priority order
        result = exact_with_role + exact_no_role + partial_with_role + partial_no_role

        # Track synergy for selected skills
        for skill in result:
            self.track_synergy(skill.skill_id, task_type)

        return result

    def find_by_pattern(self, pattern_name: str) -> List[Skill]:
        """
        Find skills that use a specific pattern.

        Args:
            pattern_name: The pattern name to search for

        Returns:
            List of skills using the pattern
        """
        skill_ids = self._pattern_index.get(pattern_name, [])
        return [self._skills[sid] for sid in skill_ids if sid in self._skills]

    def register_skill(self, skill: Skill) -> str:
        """
        Register a new skill in the library.

        Args:
            skill: The Skill to register

        Returns:
            The skill_id of the registered skill

        Raises:
            ValueError: If a skill with the same ID already exists
        """
        if skill.skill_id in self._skills:
            raise ValueError(f"Skill already exists: {skill.skill_id}")

        self._skills[skill.skill_id] = skill

        # Index patterns
        for pattern in skill.reusable_patterns:
            if pattern.pattern_name not in self._pattern_index:
                self._pattern_index[pattern.pattern_name] = []
            if skill.skill_id not in self._pattern_index[pattern.pattern_name]:
                self._pattern_index[pattern.pattern_name].append(skill.skill_id)

        self._logger.info(f"Registered skill: {skill.skill_id}")
        return skill.skill_id

    def update_skill(self, skill_id: str, updates: Dict[str, Any]) -> bool:
        """
        Update an existing skill.

        Args:
            skill_id: The ID of the skill to update
            updates: Dictionary of fields to update

        Returns:
            True if update succeeded, False if skill not found
        """
        if skill_id not in self._skills:
            return False

        skill = self._skills[skill_id]
        current_data = skill.to_dict()

        # Apply updates
        for key, value in updates.items():
            if key == "reusable_patterns" and isinstance(value, list):
                # Convert pattern dicts to ReusablePattern objects
                patterns = []
                for p in value:
                    if isinstance(p, dict):
                        patterns.append(ReusablePattern.from_dict(p))
                    elif isinstance(p, ReusablePattern):
                        patterns.append(p)
                current_data[key] = [p.to_dict() for p in patterns]
            elif key == "skill_id":
                # Don't allow changing skill_id
                continue
            else:
                current_data[key] = value

        # Re-create skill with updated data
        updated_skill = Skill.from_dict(current_data)
        self._skills[skill_id] = updated_skill

        # Re-index patterns
        self._reindex_patterns()

        self._logger.info(f"Updated skill: {skill_id}")
        return True

    def _reindex_patterns(self) -> None:
        """Rebuild the pattern index."""
        self._pattern_index.clear()
        for skill in self._skills.values():
            for pattern in skill.reusable_patterns:
                if pattern.pattern_name not in self._pattern_index:
                    self._pattern_index[pattern.pattern_name] = []
                if skill.skill_id not in self._pattern_index[pattern.pattern_name]:
                    self._pattern_index[pattern.pattern_name].append(skill.skill_id)

    def validate_catalog(self) -> ValidationResult:
        """
        Validate the current catalog state.

        Returns:
            ValidationResult with validation findings
        """
        # Build catalog dict from current skills
        catalog_data = {
            "version": "1.0.0",
            "skills": [s.to_dict() for s in self._skills.values()]
        }

        return self._validator.validate_catalog(catalog_data)

    def track_synergy(self, skill_id: str, task_type: str) -> None:
        """
        Track synergy usage for a skill.

        Emits PATTERN_REUSED event when a skill with applicable_to >= 2
        is selected for a new task type.

        Args:
            skill_id: The skill being used
            task_type: The task type it's being used for
        """
        if skill_id not in self._skills:
            return

        skill = self._skills[skill_id]

        # Initialize synergy record if needed
        if skill_id not in self._synergy_records:
            self._synergy_records[skill_id] = SynergyRecord(skill_id=skill_id)

        record = self._synergy_records[skill_id]
        is_new_task_type = task_type not in record.task_types

        # Record the use
        record.record_use(task_type)

        # Emit PATTERN_REUSED event if skill has synergy and used for new task type
        if skill.has_synergy() and is_new_task_type and self._event_bus:
            self._event_bus.emit_simple(
                event_type="PATTERN_REUSED",
                data={
                    "skill_id": skill_id,
                    "task_type": task_type,
                    "task_types_count": len(record.task_types),
                    "use_count": record.use_count,
                    "synergy_score": len(record.task_types)
                },
                source="SkillLibrary"
            )
            self._logger.debug(
                f"Emitted PATTERN_REUSED for skill {skill_id} "
                f"(used for {len(record.task_types)} task types)"
            )

    def get_synergy_stats(self) -> Dict[str, Any]:
        """
        Get synergy statistics for all skills.

        Returns:
            Dictionary with synergy statistics
        """
        stats = {
            "total_skills": len(self._skills),
            "skills_with_synergy": sum(
                1 for s in self._skills.values() if s.has_synergy()
            ),
            "patterns_count": len(self._pattern_index),
            "synergy_records": {
                skill_id: {
                    "task_types": record.task_types,
                    "use_count": record.use_count,
                    "last_used": record.last_used
                }
                for skill_id, record in self._synergy_records.items()
            }
        }

        # Calculate synergy score
        if stats["total_skills"] > 0:
            stats["synergy_percentage"] = (
                stats["skills_with_synergy"] / stats["total_skills"] * 100
            )
        else:
            stats["synergy_percentage"] = 0.0

        return stats

    def list_skills(self) -> List[str]:
        """
        List all skill IDs in the library.

        Returns:
            List of skill IDs
        """
        return list(self._skills.keys())

    def list_patterns(self) -> List[str]:
        """
        List all pattern names in the library.

        Returns:
            List of pattern names
        """
        return list(self._pattern_index.keys())

    def get_skills_by_task_type(self, task_type: str) -> List[Skill]:
        """
        Get all skills applicable to a specific task type.

        Args:
            task_type: The task type to match

        Returns:
            List of applicable skills
        """
        result = []
        for skill in self._skills.values():
            if skill.is_applicable(task_type):
                result.append(skill)
        return result

    def get_skills_by_role(self, role: str) -> List[Skill]:
        """
        Get all skills matching a specific role.

        Args:
            role: The role to match

        Returns:
            List of matching skills
        """
        result = []
        for skill in self._skills.values():
            if skill.matches_role(role):
                result.append(skill)
        return result

    def export_catalog(self, path: str) -> None:
        """
        Export the current catalog to a YAML file.

        Args:
            path: Path to write the catalog to
        """
        catalog_data = {
            "version": "1.0.0",
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "skills": [s.to_dict() for s in sorted(
                self._skills.values(),
                key=lambda s: s.skill_id
            )]
        }

        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(catalog_data, f, default_flow_style=False, sort_keys=True)

        self._logger.info(f"Exported catalog to {path}")


def create_skill_library(
    config: Dict[str, Any] = None,
    event_bus: 'EventBus' = None
) -> SkillLibrary:
    """
    Factory function to create a SkillLibrary.

    Args:
        config: Configuration dictionary
        event_bus: Optional EventBus for events

    Returns:
        SkillLibrary instance
    """
    return SkillLibrary(config or {}, event_bus)
