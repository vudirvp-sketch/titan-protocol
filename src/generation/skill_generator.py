"""Skill Generator for TITAN Protocol (ITEM-B015).

Fixed implementation with real ONTOLOGY validation, comprehensive
self-refine logic, and actual adaptation_matrix lookup from presets.

Original defects fixed:
- _is_valid_enum_value() was return True — now validates against TaskType ONTOLOGY
- _self_refine() was minimal — now checks DEPENDS_ON, GAP_TAG, Enum, adaptation_matrix
- _apply_adaptation() had no lookup — now loads from preset workflow.yaml
"""

from __future__ import annotations
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any


@dataclass
class SkillSpec:
    """Specification for a generated skill.
    
    Attributes:
        skill_id: Unique skill identifier
        target_type: Target TaskType value
        patterns: List of composed pattern definitions
        adaptation_rules: Rules from the adaptation matrix
        validated: Whether the spec passes self-refinement
        refinement_issues: Issues found during refinement
    """
    skill_id: str
    target_type: str
    patterns: List[Dict[str, Any]] = field(default_factory=list)
    adaptation_rules: List[Dict[str, Any]] = field(default_factory=list)
    validated: bool = False
    refinement_issues: List[str] = field(default_factory=list)


class SkillGenerator:
    """Generate skills from pattern compositions with real validation.
    
    ITEM-B015: Fixed SkillGenerator with:
    - _is_valid_enum_value() validates against TaskType ONTOLOGY (was return True)
    - _self_refine() checks DEPENDS_ON, GAP_TAG, Enum, adaptation_matrix (was minimal)
    - _apply_adaptation() performs real adaptation_matrix lookup from presets
    - compose_patterns() supports DEP_AUDIT target
    """
    
    def __init__(self, config: Optional[Dict] = None):
        """Initialize SkillGenerator.
        
        Args:
            config: Optional configuration dictionary.
        """
        self.config = config or {}
        self._task_type_values = self._load_task_type_values()
        self._gap_tag_registry = self._load_gap_tag_registry()
    
    def _load_task_type_values(self) -> set:
        """Load valid TaskType values from ONTOLOGY.
        
        Returns:
            Set of valid TaskType value strings.
        """
        try:
            from src.orchestrator.universal_router import TaskType
            return {t.value for t in TaskType}
        except ImportError:
            return set()
    
    def _load_gap_tag_registry(self) -> set:
        """Load valid gap tags from gap registry.
        
        Returns:
            Set of valid gap tag strings.
        """
        try:
            reg_path = Path("src/gap_events/gap_registry.yaml")
            if reg_path.exists():
                reg = yaml.safe_load(reg_path.read_text())
                return {g["gap_id"] for g in reg.get("gap_types", [])}
        except Exception:
            pass
        return set()
    
    def _is_valid_enum_value(self, value: str) -> bool:
        """Validate value against TaskType ONTOLOGY.
        
        FIXED: Original was `return True` unconditionally.
        Now performs actual ONTOLOGY validation.
        
        Args:
            value: Task type value string to validate.
            
        Returns:
            True if value is in TaskType ONTOLOGY or ONTOLOGY is unavailable.
        """
        if not self._task_type_values:
            return True  # Fallback if ONTOLOGY not available
        return value in self._task_type_values
    
    def _self_refine(self, spec: SkillSpec) -> SkillSpec:
        """Comprehensive self-refinement of a skill specification.
        
        FIXED: Original had only basic length check.
        Now checks 5 categories:
        1. DEPENDS_ON resolution — all dependencies must exist in composed patterns
        2. GAP_TAG validation — tags must be in gap_registry
        3. Enum validation — target_type must be in TaskType ONTOLOGY
        4. Adaptation matrix consistency — no empty rules
        5. Non-empty output validation — at least one pattern composed
        
        Args:
            spec: SkillSpec to refine.
            
        Returns:
            Updated SkillSpec with validation results.
        """
        issues = []
        
        # Check 1: DEPENDS_ON resolution
        unresolved_deps = []
        for pattern in spec.patterns:
            for dep in pattern.get("depends_on", []):
                dep_found = any(
                    p.get("pat_id") == dep for p in spec.patterns
                )
                if not dep_found:
                    unresolved_deps.append(dep)
        if unresolved_deps:
            issues.append(f"Unresolved DEPENDS_ON: {unresolved_deps}")
        
        # Check 2: GAP_TAG validation
        for pattern in spec.patterns:
            for tag in pattern.get("gap_tags", []):
                if self._gap_tag_registry and tag not in self._gap_tag_registry:
                    issues.append(f"Unknown GAP_TAG: {tag} in {pattern.get('pat_id')}")
        
        # Check 3: Enum validation
        if not self._is_valid_enum_value(spec.target_type):
            issues.append(f"Invalid target_type enum value: {spec.target_type}")
        
        # Check 4: Adaptation matrix consistency
        for rule in spec.adaptation_rules:
            if not rule.get("rule"):
                issues.append(f"Empty adaptation rule in pattern_type: {rule.get('pattern_type')}")
        
        # Check 5: Non-empty output validation
        if not spec.patterns:
            issues.append("No patterns composed")
        
        spec.refinement_issues = issues
        spec.validated = len(issues) == 0
        return spec
    
    def _apply_adaptation(self, spec: SkillSpec, preset_id: str) -> SkillSpec:
        """Apply adaptation matrix from preset.
        
        FIXED: Original had no adaptation_matrix lookup.
        Now loads the preset workflow.yaml and applies matching rules.
        
        Args:
            spec: SkillSpec to apply adaptation to.
            preset_id: Preset identifier to load adaptation_matrix from.
            
        Returns:
            Updated SkillSpec with adaptation rules applied.
        """
        preset_path = Path(f"presets/{preset_id}/workflow.yaml")
        if not preset_path.exists():
            spec.refinement_issues.append(f"Preset not found: {preset_id}")
            return spec
        
        try:
            preset = yaml.safe_load(preset_path.read_text())
        except yaml.YAMLError as e:
            spec.refinement_issues.append(f"Preset YAML error: {e}")
            return spec
        
        matrix = preset.get("adaptation_matrix", [])
        
        for entry in matrix:
            if entry.get("status") == "DEFERRED":
                continue
            if entry.get("pattern_type") == spec.target_type:
                spec.adaptation_rules = entry.get("adaptation_rules", [])
                break
        
        return spec
    
    def compose_patterns(
        self,
        target_type: str,
        pattern_ids: List[str],
        preset_id: Optional[str] = None,
    ) -> SkillSpec:
        """Compose patterns into a skill specification.
        
        Args:
            target_type: Target TaskType value (e.g., 'dep_audit', 'code_gen').
            pattern_ids: List of pattern IDs to compose (e.g., ['PAT-01', 'PAT-42']).
            preset_id: Optional preset ID for adaptation matrix lookup.
            
        Returns:
            SkillSpec with composed patterns, optionally with adaptation rules applied
            and self-refinement completed.
        """
        spec = SkillSpec(skill_id=f"skill_{target_type}", target_type=target_type)
        
        # Load canonical patterns
        schema_path = Path("src/schema/canonical_patterns.yaml")
        if schema_path.exists():
            try:
                schema = yaml.safe_load(schema_path.read_text())
                for pat in schema.get("patterns", []):
                    if pat["pat_id"] in pattern_ids:
                        spec.patterns.append(pat)
            except yaml.YAMLError:
                pass
        
        # Apply adaptation if preset specified
        if preset_id:
            spec = self._apply_adaptation(spec, preset_id)
        
        # Self-refine
        spec = self._self_refine(spec)
        
        return spec
