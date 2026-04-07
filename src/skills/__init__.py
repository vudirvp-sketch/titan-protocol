"""
TITAN Protocol Skills Module.

ITEM-SKILL-01: SkillLibrary with Catalog support.

This module provides skill management for the TITAN Protocol:
- Skill and ReusablePattern dataclasses
- SkillLibrary for catalog management
- CatalogValidator for validation

Example:
    >>> from src.skills import SkillLibrary, Skill
    >>> from src.events import EventBus
    >>>
    >>> # Create and load library
    >>> bus = EventBus()
    >>> config = {"catalog_path": "skills/catalog.yaml"}
    >>> library = SkillLibrary(config, bus)
    >>>
    >>> # Select skills for a task
    >>> skills = library.select_skills("AUDIT_CODE", ["architect"])
    >>> for skill in skills:
    ...     print(skill.skill_id, skill.description)
    >>>
    >>> # Register a new skill
    >>> new_skill = Skill(
    ...     skill_id="my_custom_skill",
    ...     description="Custom skill for special tasks",
    ...     applicable_to=["CUSTOM_TASK"],
    ...     role_hints=["developer"]
    ... )
    >>> library.register_skill(new_skill)

Author: TITAN FUSE Team
Version: 3.5.0
"""

# Core dataclasses
from .skill import (
    Skill,
    ReusablePattern,
)

# Validation utilities
from .catalog_validator import (
    CatalogValidator,
    CoverageReport,
    ValidationError,
    ValidationResult,
    create_validator,
)

# Main library class
from .skill_library import (
    SkillLibrary,
    SynergyRecord,
    create_skill_library,
)

__all__ = [
    # Dataclasses
    'Skill',
    'ReusablePattern',

    # Validation
    'CatalogValidator',
    'CoverageReport',
    'ValidationError',
    'ValidationResult',
    'create_validator',

    # Library
    'SkillLibrary',
    'SynergyRecord',
    'create_skill_library',
]

__version__ = '3.5.0'
