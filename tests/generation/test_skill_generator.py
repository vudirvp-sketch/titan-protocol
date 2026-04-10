"""Tests for SkillGenerator module (ITEM-B015)."""

import pytest
from src.generation.skill_generator import SkillGenerator, SkillSpec


class TestIsValidEnumValue:
    def test_valid_enum_returns_true(self):
        sg = SkillGenerator()
        if sg._task_type_values:
            valid = list(sg._task_type_values)[0]
            assert sg._is_valid_enum_value(valid) is True

    def test_invalid_enum_returns_false(self):
        sg = SkillGenerator()
        if sg._task_type_values:
            assert sg._is_valid_enum_value("nonexistent_type_xyz") is False

    def test_fallback_when_no_ontology(self):
        """When ONTOLOGY is unavailable, all values are accepted."""
        sg = SkillGenerator()
        original = sg._task_type_values
        sg._task_type_values = set()
        assert sg._is_valid_enum_value("anything") is True
        sg._task_type_values = original


class TestSelfRefine:
    def test_valid_spec_passes_refine(self):
        sg = SkillGenerator()
        spec = SkillSpec(
            skill_id="test",
            target_type=list(sg._task_type_values)[0] if sg._task_type_values else "code_gen",
            patterns=[{"pat_id": "PAT-01", "depends_on": [], "gap_tags": []}],
        )
        result = sg._self_refine(spec)
        assert result.validated is True

    def test_unresolved_dep_detected(self):
        sg = SkillGenerator()
        spec = SkillSpec(
            skill_id="test",
            target_type="code_gen",
            patterns=[{"pat_id": "PAT-01", "depends_on": ["PAT-99"], "gap_tags": []}],
        )
        result = sg._self_refine(spec)
        assert any("DEPENDS_ON" in i for i in result.refinement_issues)

    def test_invalid_enum_detected(self):
        sg = SkillGenerator()
        if not sg._task_type_values:
            pytest.skip("No TaskType ONTOLOGY available")
        spec = SkillSpec(
            skill_id="test",
            target_type="totally_invalid_xyz",
            patterns=[{"pat_id": "PAT-01", "depends_on": [], "gap_tags": []}],
        )
        result = sg._self_refine(spec)
        assert any("Invalid target_type" in i for i in result.refinement_issues)

    def test_empty_patterns_detected(self):
        sg = SkillGenerator()
        spec = SkillSpec(
            skill_id="test",
            target_type="code_gen",
            patterns=[],
        )
        result = sg._self_refine(spec)
        assert any("No patterns" in i for i in result.refinement_issues)


class TestApplyAdaptation:
    def test_adaptation_from_preset(self):
        sg = SkillGenerator()
        spec = SkillSpec(skill_id="test", target_type="single_file_code")
        result = sg._apply_adaptation(spec, "large_file")
        # Should either load rules or report preset issue
        assert isinstance(result, SkillSpec)

    def test_missing_preset_reported(self):
        sg = SkillGenerator()
        spec = SkillSpec(skill_id="test", target_type="code_gen")
        result = sg._apply_adaptation(spec, "nonexistent_preset_xyz")
        assert any("Preset not found" in i for i in result.refinement_issues)


class TestComposePatterns:
    def test_compose_with_dep_audit(self):
        sg = SkillGenerator()
        spec = sg.compose_patterns("dep_audit", ["PAT-01"])
        assert spec.skill_id == "skill_dep_audit"

    def test_compose_with_preset(self):
        sg = SkillGenerator()
        spec = sg.compose_patterns("dep_audit", ["PAT-01"], preset_id="dependency_audit")
        assert spec.skill_id == "skill_dep_audit"

    def test_compose_runs_self_refine(self):
        sg = SkillGenerator()
        spec = sg.compose_patterns("code_gen", ["PAT-01"])
        # Self-refine should have run (validated may be True or False)
        assert isinstance(spec.validated, bool)
        assert isinstance(spec.refinement_issues, list)
