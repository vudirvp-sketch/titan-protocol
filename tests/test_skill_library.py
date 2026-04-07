"""
Tests for SkillLibrary and related components.

ITEM-SKILL-01: Test coverage for skill catalog management.

This module tests:
- ReusablePattern dataclass
- Skill dataclass
- SkillLibrary class
- CatalogValidator class

Author: TITAN FUSE Team
Version: 3.6.0
"""

import pytest
import tempfile
import os
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.skills.skill import Skill, ReusablePattern
from src.skills.skill_library import SkillLibrary, SynergyRecord, create_skill_library
from src.skills.catalog_validator import (
    CatalogValidator,
    ValidationResult,
    ValidationError,
    CoverageReport
)


# ============================================================================
# ReusablePattern Tests
# ============================================================================

class TestReusablePattern:
    """Tests for ReusablePattern dataclass."""

    def test_pattern_creation(self):
        """Test creating a ReusablePattern."""
        pattern = ReusablePattern(
            pattern_name="chunk_boundary_detection",
            implementation="AST_based+semantic_markers",
            validation_chain=["ast_parser", "schema_check"]
        )
        
        assert pattern.pattern_name == "chunk_boundary_detection"
        assert pattern.implementation == "AST_based+semantic_markers"
        assert pattern.validation_chain == ["ast_parser", "schema_check"]

    def test_pattern_to_dict(self):
        """Test pattern serialization."""
        pattern = ReusablePattern(
            pattern_name="test_pattern",
            implementation="test_implementation",
            validation_chain=["validator1", "validator2"]
        )
        
        result = pattern.to_dict()
        
        assert result["pattern_name"] == "test_pattern"
        assert result["implementation"] == "test_implementation"
        assert result["validation_chain"] == ["validator1", "validator2"]

    def test_pattern_from_dict(self):
        """Test pattern deserialization."""
        data = {
            "pattern_name": "restored_pattern",
            "implementation": "restored_impl",
            "validation_chain": ["v1", "v2", "v3"]
        }
        
        pattern = ReusablePattern.from_dict(data)
        
        assert pattern.pattern_name == "restored_pattern"
        assert pattern.implementation == "restored_impl"
        assert pattern.validation_chain == ["v1", "v2", "v3"]

    def test_pattern_hash_and_equality(self):
        """Test pattern hashing and equality."""
        pattern1 = ReusablePattern(
            pattern_name="same_name",
            implementation="impl1",
            validation_chain=["v1"]
        )
        pattern2 = ReusablePattern(
            pattern_name="same_name",
            implementation="impl2",
            validation_chain=["v2"]
        )
        pattern3 = ReusablePattern(
            pattern_name="different_name",
            implementation="impl1",
            validation_chain=["v1"]
        )
        
        # Equality based on pattern_name
        assert pattern1 == pattern2
        assert pattern1 != pattern3
        
        # Hashability
        pattern_set = {pattern1, pattern3}
        assert len(pattern_set) == 2

    def test_pattern_default_validation_chain(self):
        """Test that validation_chain defaults to empty list."""
        pattern = ReusablePattern(
            pattern_name="no_chain",
            implementation="impl"
        )
        
        assert pattern.validation_chain == []


# ============================================================================
# Skill Tests
# ============================================================================

class TestSkill:
    """Tests for Skill dataclass."""

    def test_skill_creation(self):
        """Test creating a Skill."""
        skill = Skill(
            skill_id="test_skill",
            description="A test skill",
            applicable_to=["TASK_A", "TASK_B"],
            role_hints=["developer", "architect"],
            required_tools=["tool1", "tool2"]
        )
        
        assert skill.skill_id == "test_skill"
        assert skill.description == "A test skill"
        assert skill.applicable_to == ["TASK_A", "TASK_B"]
        assert skill.role_hints == ["developer", "architect"]
        assert skill.required_tools == ["tool1", "tool2"]

    def test_skill_is_applicable_exact_match(self):
        """Test exact task type matching."""
        skill = Skill(
            skill_id="test",
            description="test",
            applicable_to=["AUDIT_CODE", "REVIEW_PLAN"]
        )
        
        assert skill.is_applicable("AUDIT_CODE") is True
        assert skill.is_applicable("REVIEW_PLAN") is True
        assert skill.is_applicable("UNKNOWN_TASK") is False

    def test_skill_is_applicable_case_insensitive(self):
        """Test case-insensitive task type matching."""
        skill = Skill(
            skill_id="test",
            description="test",
            applicable_to=["AUDIT_CODE"]
        )
        
        assert skill.is_applicable("audit_code") is True
        assert skill.is_applicable("Audit_Code") is True
        assert skill.is_applicable("AUDIT_CODE") is True

    def test_skill_is_applicable_partial_match(self):
        """Test partial task type matching."""
        skill = Skill(
            skill_id="test",
            description="test",
            applicable_to=["CODE"]  # Will match CODE_REVIEW, AUDIT_CODE
        )
        
        assert skill.is_applicable("CODE_REVIEW") is True
        assert skill.is_applicable("AUDIT_CODE") is True

    def test_skill_is_applicable_empty(self):
        """Test matching with empty task type."""
        skill = Skill(
            skill_id="test",
            description="test",
            applicable_to=["TASK_A"]
        )
        
        assert skill.is_applicable("") is False
        assert skill.is_applicable(None) is False

    def test_skill_matches_role(self):
        """Test role matching."""
        skill = Skill(
            skill_id="test",
            description="test",
            role_hints=["senior-python-dev", "architect"]
        )
        
        assert skill.matches_role("senior-python-dev") is True
        assert skill.matches_role("architect") is True
        assert skill.matches_role("ARCHITECT") is True  # case-insensitive
        assert skill.matches_role("python-dev") is True  # partial match
        assert skill.matches_role("unknown") is False

    def test_skill_matches_role_empty(self):
        """Test role matching with empty role."""
        skill = Skill(
            skill_id="test",
            description="test",
            role_hints=["developer"]
        )
        
        assert skill.matches_role("") is False
        assert skill.matches_role(None) is False

    def test_skill_to_dict(self):
        """Test skill serialization."""
        pattern = ReusablePattern(
            pattern_name="test_pattern",
            implementation="impl"
        )
        skill = Skill(
            skill_id="test_skill",
            description="test description",
            applicable_to=["TASK_A"],
            reusable_patterns=[pattern],
            role_hints=["dev"],
            required_tools=["tool1"],
            metadata={"key": "value"}
        )
        
        result = skill.to_dict()
        
        assert result["skill_id"] == "test_skill"
        assert result["description"] == "test description"
        assert result["applicable_to"] == ["TASK_A"]
        assert len(result["reusable_patterns"]) == 1
        assert result["role_hints"] == ["dev"]
        assert result["required_tools"] == ["tool1"]
        assert result["metadata"] == {"key": "value"}

    def test_skill_from_dict(self):
        """Test skill deserialization."""
        data = {
            "skill_id": "restored_skill",
            "description": "restored description",
            "applicable_to": ["TASK_X"],
            "reusable_patterns": [
                {
                    "pattern_name": "pattern1",
                    "implementation": "impl1"
                }
            ],
            "role_hints": ["admin"],
            "required_tools": ["tool2"],
            "validation_chain": ["v1"],
            "metadata": {"extra": "data"}
        }
        
        skill = Skill.from_dict(data)
        
        assert skill.skill_id == "restored_skill"
        assert skill.description == "restored description"
        assert skill.applicable_to == ["TASK_X"]
        assert len(skill.reusable_patterns) == 1
        assert skill.reusable_patterns[0].pattern_name == "pattern1"
        assert skill.role_hints == ["admin"]
        assert skill.required_tools == ["tool2"]

    def test_skill_has_synergy(self):
        """Test synergy detection."""
        skill_with_synergy = Skill(
            skill_id="synergy",
            description="test",
            applicable_to=["TASK_A", "TASK_B"]
        )
        
        skill_without_synergy = Skill(
            skill_id="no_synergy",
            description="test",
            applicable_to=["TASK_A"]
        )
        
        assert skill_with_synergy.has_synergy() is True
        assert skill_without_synergy.has_synergy() is False

    def test_skill_get_hash(self):
        """Test skill hash generation."""
        skill = Skill(
            skill_id="test",
            description="test"
        )
        
        hash1 = skill.get_hash()
        hash2 = skill.get_hash()
        
        assert hash1 == hash2
        assert len(hash1) == 16

    def test_skill_equality(self):
        """Test skill equality based on skill_id."""
        skill1 = Skill(skill_id="same", description="desc1")
        skill2 = Skill(skill_id="same", description="desc2")
        skill3 = Skill(skill_id="different", description="desc1")
        
        assert skill1 == skill2
        assert skill1 != skill3

    def test_skill_repr_and_str(self):
        """Test string representations."""
        skill = Skill(
            skill_id="test_skill",
            description="Test description",
            role_hints=["dev", "admin"]
        )
        
        assert "test_skill" in repr(skill)
        assert "Test description" in str(skill)


# ============================================================================
# SynergyRecord Tests
# ============================================================================

class TestSynergyRecord:
    """Tests for SynergyRecord dataclass."""

    def test_synergy_record_creation(self):
        """Test creating a SynergyRecord."""
        record = SynergyRecord(skill_id="test_skill")
        
        assert record.skill_id == "test_skill"
        assert record.task_types == []
        assert record.use_count == 0
        assert record.last_used is None

    def test_synergy_record_use(self):
        """Test recording skill usage."""
        record = SynergyRecord(skill_id="test_skill")
        
        record.record_use("TASK_A")
        
        assert "TASK_A" in record.task_types
        assert record.use_count == 1
        assert record.last_used is not None

    def test_synergy_record_multiple_uses(self):
        """Test recording multiple uses."""
        record = SynergyRecord(skill_id="test_skill")
        
        record.record_use("TASK_A")
        record.record_use("TASK_B")
        record.record_use("TASK_A")  # Duplicate
        
        assert len(record.task_types) == 2  # TASK_A, TASK_B
        assert record.use_count == 3


# ============================================================================
# CatalogValidator Tests
# ============================================================================

class TestCatalogValidator:
    """Tests for CatalogValidator."""

    def test_validate_valid_catalog(self):
        """Test validation of a valid catalog."""
        validator = CatalogValidator()
        catalog = {
            "version": "1.0.0",
            "skills": [
                {
                    "skill_id": "skill1",
                    "description": "Test skill",
                    "applicable_to": ["TASK_A", "TASK_B"],
                    "role_hints": ["dev"]
                }
            ]
        }
        
        result = validator.validate_catalog(catalog)
        
        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_validate_missing_skill_id(self):
        """Test validation catches missing skill_id."""
        validator = CatalogValidator()
        catalog = {
            "version": "1.0.0",
            "skills": [
                {
                    "description": "Missing skill_id",
                    "applicable_to": ["TASK_A"]
                }
            ]
        }
        
        result = validator.validate_catalog(catalog)
        
        assert result.is_valid is False
        assert len(result.errors) > 0

    def test_validate_missing_applicable_to(self):
        """Test validation catches missing applicable_to."""
        validator = CatalogValidator()
        catalog = {
            "version": "1.0.0",
            "skills": [
                {
                    "skill_id": "skill1",
                    "description": "Missing applicable_to"
                }
            ]
        }
        
        result = validator.validate_catalog(catalog)
        
        # Should have errors about missing applicable_to
        assert result.is_valid is False
        assert len(result.errors) > 0

    def test_detect_missing_synergy(self):
        """Test detection of skills without synergy."""
        validator = CatalogValidator()
        
        skills = [
            Skill(skill_id="synergy", description="test", applicable_to=["A", "B"]),
            Skill(skill_id="no_synergy", description="test", applicable_to=["A"])
        ]
        
        missing = validator.detect_missing_synergy(skills)
        
        assert "no_synergy" in missing
        assert "synergy" not in missing

    def test_check_applicable_to_coverage(self):
        """Test coverage checking."""
        validator = CatalogValidator()
        
        skills = [
            Skill(skill_id="skill1", description="test", applicable_to=["TASK_A", "TASK_B"]),
            Skill(skill_id="skill2", description="test", applicable_to=["TASK_B", "TASK_C"])
        ]
        task_types = ["TASK_A", "TASK_B", "TASK_C", "TASK_D"]
        
        report = validator.check_applicable_to_coverage(skills, task_types)
        
        assert "TASK_A" in report.covered_task_types
        assert "TASK_B" in report.covered_task_types
        assert "TASK_C" in report.covered_task_types
        assert "TASK_D" in report.uncovered_task_types


# ============================================================================
# SkillLibrary Tests
# ============================================================================

class TestSkillLibrary:
    """Tests for SkillLibrary class."""

    @pytest.fixture
    def sample_catalog(self, tmp_path):
        """Create a sample catalog file."""
        catalog_content = """
version: "1.0.0"
generated_at: "2026-04-08T00:00:00Z"

skills:
  - skill_id: "skill_a"
    description: "Skill A for testing"
    applicable_to:
      - "TASK_A"
      - "TASK_B"
    role_hints:
      - "developer"
      - "architect"
    required_tools:
      - "tool1"
    reusable_patterns:
      - pattern_name: "pattern1"
        implementation: "impl1"
        validation_chain: ["v1"]

  - skill_id: "skill_b"
    description: "Skill B for testing"
    applicable_to:
      - "TASK_B"
      - "TASK_C"
    role_hints:
      - "reviewer"
    required_tools:
      - "tool2"

  - skill_id: "skill_c"
    description: "Skill C with single task"
    applicable_to:
      - "TASK_D"
    role_hints:
      - "developer"
"""
        catalog_path = tmp_path / "catalog.yaml"
        catalog_path.write_text(catalog_content)
        return str(catalog_path)

    def test_load_catalog(self, sample_catalog):
        """Test loading a catalog file."""
        library = SkillLibrary({"catalog_path": sample_catalog})
        
        assert len(library.list_skills()) == 3
        assert library.get_skill("skill_a") is not None
        assert library.get_skill("skill_b") is not None
        assert library.get_skill("skill_c") is not None

    def test_get_skill(self, sample_catalog):
        """Test getting a skill by ID."""
        library = SkillLibrary({"catalog_path": sample_catalog})
        
        skill = library.get_skill("skill_a")
        
        assert skill is not None
        assert skill.skill_id == "skill_a"
        assert skill.description == "Skill A for testing"

    def test_get_skill_not_found(self, sample_catalog):
        """Test getting a non-existent skill."""
        library = SkillLibrary({"catalog_path": sample_catalog})
        
        skill = library.get_skill("nonexistent")
        
        assert skill is None

    def test_select_skills_exact_match(self, sample_catalog):
        """Test skill selection with exact task type match."""
        library = SkillLibrary({"catalog_path": sample_catalog})
        
        skills = library.select_skills("TASK_A")
        
        assert len(skills) >= 1
        assert any(s.skill_id == "skill_a" for s in skills)

    def test_select_skills_with_role_match(self, sample_catalog):
        """Test skill selection with role matching."""
        library = SkillLibrary({"catalog_path": sample_catalog})
        
        skills = library.select_skills("TASK_B", ["developer"])
        
        # skill_a should come first (exact match + role match)
        assert len(skills) >= 1
        assert skills[0].skill_id == "skill_a"

    def test_select_skills_priority_order(self, sample_catalog):
        """Test selection priority ordering."""
        library = SkillLibrary({"catalog_path": sample_catalog})
        
        # Without role hints, should get skills in priority order
        skills = library.select_skills("TASK_B")
        
        # Both skill_a and skill_b match TASK_B
        skill_ids = [s.skill_id for s in skills]
        assert "skill_a" in skill_ids
        assert "skill_b" in skill_ids

    def test_find_by_pattern(self, sample_catalog):
        """Test finding skills by pattern."""
        library = SkillLibrary({"catalog_path": sample_catalog})
        
        skills = library.find_by_pattern("pattern1")
        
        assert len(skills) == 1
        assert skills[0].skill_id == "skill_a"

    def test_find_by_pattern_not_found(self, sample_catalog):
        """Test finding skills by non-existent pattern."""
        library = SkillLibrary({"catalog_path": sample_catalog})
        
        skills = library.find_by_pattern("nonexistent_pattern")
        
        assert len(skills) == 0

    def test_register_skill(self, sample_catalog):
        """Test registering a new skill."""
        library = SkillLibrary({"catalog_path": sample_catalog})
        
        new_skill = Skill(
            skill_id="new_skill",
            description="A new skill",
            applicable_to=["TASK_X"],
            role_hints=["tester"]
        )
        
        skill_id = library.register_skill(new_skill)
        
        assert skill_id == "new_skill"
        assert library.get_skill("new_skill") is not None

    def test_register_duplicate_skill(self, sample_catalog):
        """Test that registering a duplicate skill fails."""
        library = SkillLibrary({"catalog_path": sample_catalog})
        
        duplicate = Skill(
            skill_id="skill_a",  # Already exists
            description="Duplicate"
        )
        
        with pytest.raises(ValueError):
            library.register_skill(duplicate)

    def test_update_skill(self, sample_catalog):
        """Test updating a skill."""
        library = SkillLibrary({"catalog_path": sample_catalog})
        
        result = library.update_skill("skill_a", {
            "description": "Updated description"
        })
        
        assert result is True
        skill = library.get_skill("skill_a")
        assert skill.description == "Updated description"

    def test_update_skill_not_found(self, sample_catalog):
        """Test updating a non-existent skill."""
        library = SkillLibrary({"catalog_path": sample_catalog})
        
        result = library.update_skill("nonexistent", {"description": "test"})
        
        assert result is False

    def test_track_synergy(self, sample_catalog):
        """Test synergy tracking."""
        mock_event_bus = Mock()
        library = SkillLibrary({"catalog_path": sample_catalog}, event_bus=mock_event_bus)
        
        # Select a skill with synergy (skill_a has TASK_A, TASK_B)
        library.select_skills("TASK_A")
        
        # Should have tracked synergy
        stats = library.get_synergy_stats()
        assert "skill_a" in stats["synergy_records"]

    def test_get_synergy_stats(self, sample_catalog):
        """Test getting synergy statistics."""
        library = SkillLibrary({"catalog_path": sample_catalog})
        
        stats = library.get_synergy_stats()
        
        assert stats["total_skills"] == 3
        assert stats["skills_with_synergy"] == 2  # skill_a, skill_b
        assert stats["synergy_percentage"] == pytest.approx(66.67, rel=0.01)

    def test_list_skills(self, sample_catalog):
        """Test listing all skills."""
        library = SkillLibrary({"catalog_path": sample_catalog})
        
        skill_ids = library.list_skills()
        
        assert len(skill_ids) == 3
        assert "skill_a" in skill_ids
        assert "skill_b" in skill_ids
        assert "skill_c" in skill_ids

    def test_list_patterns(self, sample_catalog):
        """Test listing all patterns."""
        library = SkillLibrary({"catalog_path": sample_catalog})
        
        patterns = library.list_patterns()
        
        assert "pattern1" in patterns

    def test_get_skills_by_task_type(self, sample_catalog):
        """Test getting skills by task type."""
        library = SkillLibrary({"catalog_path": sample_catalog})
        
        skills = library.get_skills_by_task_type("TASK_B")
        
        assert len(skills) == 2
        skill_ids = [s.skill_id for s in skills]
        assert "skill_a" in skill_ids
        assert "skill_b" in skill_ids

    def test_get_skills_by_role(self, sample_catalog):
        """Test getting skills by role."""
        library = SkillLibrary({"catalog_path": sample_catalog})
        
        skills = library.get_skills_by_role("developer")
        
        assert len(skills) >= 2
        skill_ids = [s.skill_id for s in skills]
        assert "skill_a" in skill_ids
        assert "skill_c" in skill_ids

    def test_export_catalog(self, sample_catalog, tmp_path):
        """Test exporting catalog."""
        library = SkillLibrary({"catalog_path": sample_catalog})
        
        export_path = str(tmp_path / "exported_catalog.yaml")
        library.export_catalog(export_path)
        
        assert os.path.exists(export_path)
        
        # Load exported catalog
        library2 = SkillLibrary({"catalog_path": export_path})
        assert len(library2.list_skills()) == 3

    def test_validate_catalog(self, sample_catalog):
        """Test catalog validation."""
        library = SkillLibrary({"catalog_path": sample_catalog})
        
        result = library.validate_catalog()
        
        assert result.is_valid is True

    def test_create_skill_library_factory(self, sample_catalog):
        """Test factory function."""
        library = create_skill_library({"catalog_path": sample_catalog})
        
        assert isinstance(library, SkillLibrary)
        assert len(library.list_skills()) == 3


# ============================================================================
# Integration Tests
# ============================================================================

class TestSkillLibraryIntegration:
    """Integration tests for SkillLibrary with EventBus."""

    def test_pattern_reused_event_emitted(self, sample_catalog):
        """Test that PATTERN_REUSED event is emitted for skills with synergy."""
        mock_event_bus = Mock()
        mock_event_bus.emit_simple = Mock()
        
        library = SkillLibrary({"catalog_path": sample_catalog}, event_bus=mock_event_bus)
        
        # Select skill_a which has synergy (applicable_to >= 2)
        library.select_skills("TASK_A", ["developer"])
        
        # Event should have been emitted
        assert mock_event_bus.emit_simple.called

    @pytest.fixture
    def sample_catalog(self, tmp_path):
        """Create a sample catalog file."""
        catalog_content = """
version: "1.0.0"

skills:
  - skill_id: "skill_a"
    description: "Skill A"
    applicable_to:
      - "TASK_A"
      - "TASK_B"
    role_hints:
      - "developer"
    reusable_patterns:
      - pattern_name: "pattern1"
        implementation: "impl1"

  - skill_id: "skill_b"
    description: "Skill B"
    applicable_to:
      - "TASK_B"
    role_hints:
      - "reviewer"

  - skill_id: "skill_c"
    description: "Skill C"
    applicable_to:
      - "TASK_C"
      - "TASK_D"
      - "TASK_E"
    role_hints:
      - "developer"
"""
        catalog_path = tmp_path / "catalog.yaml"
        catalog_path.write_text(catalog_content)
        return str(catalog_path)


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
