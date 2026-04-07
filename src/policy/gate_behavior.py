"""
Gate Behavior Modifier for TITAN FUSE Protocol.

ITEM-GATE-02: Mode-Based Gate Sensitivity

Provides mode-specific gate sensitivity configuration.
Different execution modes have different tolerance levels for gaps.

Modes:
- deterministic: Strictest mode. Fails on any SEV-1 gap.
- guided_autonomy: Moderate strictness. More lenient thresholds.
- fast_prototype: Most lenient. Allows more gaps for rapid iteration.

Author: TITAN FUSE Team
Version: 3.3.0
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from enum import Enum
import logging
import copy


class ExecutionMode(Enum):
    """Execution modes with different gate sensitivity."""
    DETERMINISTIC = "deterministic"
    GUIDED_AUTONOMY = "guided_autonomy"
    FAST_PROTOTYPE = "fast_prototype"
    DIRECT = "direct"  # Default mode


@dataclass
class GateSensitivityConfig:
    """
    Sensitivity configuration for a specific mode.
    
    Attributes:
        fail_on_any_gap: Whether to fail on any unresolved gap
        warn_threshold_pct: Percentage threshold for warnings (0-100)
        max_sev1_gaps: Maximum allowed SEV-1 gaps (should always be 0)
        max_sev2_gaps: Maximum allowed SEV-2 gaps
        max_sev3_gaps: Maximum allowed SEV-3 gaps
        max_sev4_gaps: Maximum allowed SEV-4 gaps
        allow_advisory_pass: Whether advisory pass is allowed
        allow_unsafe: Whether unsafe operations are permitted
        confidence_override: Whether confidence can override gate decisions
    """
    fail_on_any_gap: bool = True
    warn_threshold_pct: float = 5.0
    max_sev1_gaps: int = 0
    max_sev2_gaps: int = 0
    max_sev3_gaps: int = 5
    max_sev4_gaps: int = 10
    allow_advisory_pass: bool = False
    allow_unsafe: bool = False
    confidence_override: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "fail_on_any_gap": self.fail_on_any_gap,
            "warn_threshold_pct": self.warn_threshold_pct,
            "max_sev1_gaps": self.max_sev1_gaps,
            "max_sev2_gaps": self.max_sev2_gaps,
            "max_sev3_gaps": self.max_sev3_gaps,
            "max_sev4_gaps": self.max_sev4_gaps,
            "allow_advisory_pass": self.allow_advisory_pass,
            "allow_unsafe": self.allow_unsafe,
            "confidence_override": self.confidence_override
        }


# Default sensitivity configurations per mode
MODE_SENSITIVITY_DEFAULTS: Dict[str, GateSensitivityConfig] = {
    "deterministic": GateSensitivityConfig(
        fail_on_any_gap=True,
        warn_threshold_pct=5.0,
        max_sev1_gaps=0,
        max_sev2_gaps=0,
        max_sev3_gaps=0,
        max_sev4_gaps=0,
        allow_advisory_pass=False,
        allow_unsafe=False,
        confidence_override=False
    ),
    "guided_autonomy": GateSensitivityConfig(
        fail_on_any_gap=False,
        warn_threshold_pct=15.0,
        max_sev1_gaps=0,
        max_sev2_gaps=2,
        max_sev3_gaps=5,
        max_sev4_gaps=10,
        allow_advisory_pass=True,
        allow_unsafe=False,
        confidence_override=True
    ),
    "fast_prototype": GateSensitivityConfig(
        fail_on_any_gap=False,
        warn_threshold_pct=30.0,
        max_sev1_gaps=0,  # Still block on SEV-1
        max_sev2_gaps=5,
        max_sev3_gaps=10,
        max_sev4_gaps=20,
        allow_advisory_pass=True,
        allow_unsafe=True,
        confidence_override=True
    ),
    "direct": GateSensitivityConfig(
        fail_on_any_gap=True,
        warn_threshold_pct=10.0,
        max_sev1_gaps=0,
        max_sev2_gaps=0,
        max_sev3_gaps=3,
        max_sev4_gaps=5,
        allow_advisory_pass=False,
        allow_unsafe=False,
        confidence_override=False
    )
}


class GateResult(Enum):
    """Result of gate evaluation (imported from gate_evaluation)."""
    PASS = "PASS"
    FAIL = "FAIL"
    ADVISORY_PASS = "ADVISORY_PASS"
    PENDING = "PENDING"


@dataclass
class ModifiedGateResult:
    """Result after applying mode-based modification."""
    original_result: GateResult
    modified_result: GateResult
    mode: str
    modifications: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_result": self.original_result.value,
            "modified_result": self.modified_result.value,
            "mode": self.mode,
            "modifications": self.modifications,
            "warnings": self.warnings
        }


class GateBehaviorModifier:
    """
    ITEM-GATE-02: Modifies gate behavior based on execution mode.
    
    This class applies mode-specific sensitivity settings to gate
    evaluation results, allowing different strictness levels for
    different use cases.
    
    Mode Behaviors:
    
    **deterministic**:
    - Strictest mode for production/critical operations
    - Fails on ANY unresolved gap (including SEV-4)
    - No advisory pass allowed
    - No confidence override
    - No unsafe operations
    
    **guided_autonomy**:
    - Moderate strictness for assisted operations
    - Allows up to 2 SEV-2 gaps
    - Advisory pass allowed with HIGH confidence
    - No unsafe operations
    
    **fast_prototype**:
    - Most lenient for rapid iteration
    - Allows more SEV-2/SEV-3/SEV-4 gaps
    - Advisory pass allowed
    - Unsafe operations permitted (with warning)
    - Confidence override enabled
    
    Usage:
        modifier = GateBehaviorModifier(config)
        
        # Get sensitivity for a mode
        sensitivity = modifier.get_sensitivity("deterministic")
        
        # Apply mode rules to a result
        modified = modifier.apply_mode_rules(result, "guided_autonomy", gaps)
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize gate behavior modifier.
        
        Args:
            config: Configuration dictionary with mode-specific settings
        """
        self.config = config or {}
        self._logger = logging.getLogger(__name__)
        
        # Load sensitivity configurations
        self._sensitivity_configs = self._load_sensitivity_configs()
    
    def _load_sensitivity_configs(self) -> Dict[str, GateSensitivityConfig]:
        """Load sensitivity configurations from config or defaults."""
        configs = copy.deepcopy(MODE_SENSITIVITY_DEFAULTS)
        
        # Override with config values if present
        gate_sensitivity = self.config.get("gate_sensitivity", {})
        
        for mode, settings in gate_sensitivity.items():
            if mode in configs:
                # Update existing config
                current = configs[mode]
                configs[mode] = GateSensitivityConfig(
                    fail_on_any_gap=settings.get("fail_on_any_gap", current.fail_on_any_gap),
                    warn_threshold_pct=settings.get("warn_threshold_pct", current.warn_threshold_pct),
                    max_sev1_gaps=settings.get("max_sev1_gaps", current.max_sev1_gaps),
                    max_sev2_gaps=settings.get("max_sev2_gaps", current.max_sev2_gaps),
                    max_sev3_gaps=settings.get("max_sev3_gaps", current.max_sev3_gaps),
                    max_sev4_gaps=settings.get("max_sev4_gaps", current.max_sev4_gaps),
                    allow_advisory_pass=settings.get("allow_advisory_pass", current.allow_advisory_pass),
                    allow_unsafe=settings.get("allow_unsafe", current.allow_unsafe),
                    confidence_override=settings.get("confidence_override", current.confidence_override)
                )
            else:
                # New mode config
                configs[mode] = GateSensitivityConfig(
                    fail_on_any_gap=settings.get("fail_on_any_gap", False),
                    warn_threshold_pct=settings.get("warn_threshold_pct", 15.0),
                    max_sev1_gaps=settings.get("max_sev1_gaps", 0),
                    max_sev2_gaps=settings.get("max_sev2_gaps", 2),
                    max_sev3_gaps=settings.get("max_sev3_gaps", 5),
                    max_sev4_gaps=settings.get("max_sev4_gaps", 10),
                    allow_advisory_pass=settings.get("allow_advisory_pass", True),
                    allow_unsafe=settings.get("allow_unsafe", False),
                    confidence_override=settings.get("confidence_override", False)
                )
        
        return configs
    
    def get_sensitivity(self, mode: str) -> GateSensitivityConfig:
        """
        Get sensitivity configuration for a mode.
        
        Args:
            mode: Execution mode name
            
        Returns:
            GateSensitivityConfig for the mode
        """
        # Normalize mode name
        mode_normalized = mode.lower().replace("-", "_").replace(" ", "_")
        
        # Map common aliases
        mode_aliases = {
            "guided_autonomy": "guided_autonomy",
            "guided autonomy": "guided_autonomy",
            "fast_prototype": "fast_prototype",
            "fast prototype": "fast_prototype",
            "fast": "fast_prototype",
            "proto": "fast_prototype"
        }
        
        mode_key = mode_aliases.get(mode_normalized, mode_normalized)
        
        if mode_key not in self._sensitivity_configs:
            self._logger.warning(
                f"Unknown mode '{mode}', using 'direct' as default"
            )
            mode_key = "direct"
        
        return self._sensitivity_configs[mode_key]
    
    def apply_mode_rules(self, result: GateResult, mode: str,
                         gaps: List[Dict[str, Any]] = None,
                         confidence: str = "MEDIUM") -> ModifiedGateResult:
        """
        Apply mode-specific rules to a gate result.
        
        This method modifies gate behavior based on mode sensitivity:
        - May upgrade FAIL to ADVISORY_PASS (for lenient modes)
        - May add warnings based on thresholds
        - May block certain operations
        
        Args:
            result: Original gate result
            mode: Execution mode
            gaps: List of gap dictionaries (for threshold checking)
            confidence: Current confidence level
            
        Returns:
            ModifiedGateResult with potentially modified result
        """
        sensitivity = self.get_sensitivity(mode)
        modifications: List[str] = []
        warnings: List[str] = []
        
        original_result = result
        modified_result = result
        
        # Count gaps by severity if provided
        gap_counts = {"SEV-1": 0, "SEV-2": 0, "SEV-3": 0, "SEV-4": 0}
        if gaps:
            for gap in gaps:
                if not gap.get("resolved", False):
                    sev = gap.get("severity", "SEV-4")
                    if sev in gap_counts:
                        gap_counts[sev] += 1
        
        # Apply mode-specific rules
        
        # RULE 1: SEV-1 always blocks (regardless of mode)
        if gap_counts["SEV-1"] > 0:
            modified_result = GateResult.FAIL
            modifications.append("SEV-1 gaps always block regardless of mode")
            warnings.append(f"{gap_counts['SEV-1']} SEV-1 gap(s) detected")
            
            self._logger.error(
                f"[gate_behavior] Mode '{mode}': SEV-1 gaps block execution"
            )
            
            return ModifiedGateResult(
                original_result=original_result,
                modified_result=modified_result,
                mode=mode,
                modifications=modifications,
                warnings=warnings
            )
        
        # RULE 2: Check fail_on_any_gap for deterministic mode
        if sensitivity.fail_on_any_gap and result != GateResult.PASS:
            total_gaps = sum(gap_counts.values())
            if total_gaps > 0:
                modifications.append(
                    f"fail_on_any_gap=True: {total_gaps} unresolved gap(s) cause FAIL"
                )
                modified_result = GateResult.FAIL
        
        # RULE 3: Check severity thresholds
        thresholds = [
            ("SEV-2", gap_counts["SEV-2"], sensitivity.max_sev2_gaps),
            ("SEV-3", gap_counts["SEV-3"], sensitivity.max_sev3_gaps),
            ("SEV-4", gap_counts["SEV-4"], sensitivity.max_sev4_gaps),
        ]
        
        for sev_name, count, max_allowed in thresholds:
            if count > max_allowed:
                modified_result = GateResult.FAIL
                modifications.append(
                    f"{sev_name} threshold exceeded: {count} > {max_allowed}"
                )
                warnings.append(f"{count} {sev_name} gap(s) exceed threshold of {max_allowed}")
        
        # RULE 4: Advisory pass handling
        if result == GateResult.FAIL and modified_result == GateResult.FAIL:
            if (sensitivity.allow_advisory_pass and 
                confidence == "HIGH" and 
                sensitivity.confidence_override):
                # Check if only SEV-3/SEV-4 gaps exist
                if gap_counts["SEV-1"] == 0 and gap_counts["SEV-2"] <= sensitivity.max_sev2_gaps:
                    modified_result = GateResult.ADVISORY_PASS
                    modifications.append(
                        "Upgraded to ADVISORY_PASS due to HIGH confidence and mode settings"
                    )
                    warnings.append("Advisory pass: gaps remain but HIGH confidence allows continuation")
        
        # RULE 5: Unsafe mode warning
        if sensitivity.allow_unsafe:
            warnings.append(
                "WARNING: Unsafe operations permitted in this mode. "
                "Use with caution in production environments."
            )
            self._logger.warning(
                f"[gate_behavior] Mode '{mode}' allows unsafe operations"
            )
        
        # RULE 6: Warn threshold check
        total_gaps = sum(gap_counts.values())
        total_possible = 100  # Normalized
        gap_pct = (total_gaps / max(total_possible, 1)) * 100
        
        if gap_pct > sensitivity.warn_threshold_pct:
            warnings.append(
                f"Gap percentage ({gap_pct:.1f}%) exceeds warn threshold "
                f"({sensitivity.warn_threshold_pct}%)"
            )
        
        # Log modification if result changed
        if modified_result != original_result:
            self._logger.info(
                f"[gate_behavior] Mode '{mode}': "
                f"{original_result.value} -> {modified_result.value}. "
                f"Modifications: {modifications}"
            )
        
        return ModifiedGateResult(
            original_result=original_result,
            modified_result=modified_result,
            mode=mode,
            modifications=modifications,
            warnings=warnings
        )
    
    def get_mode_info(self, mode: str) -> Dict[str, Any]:
        """
        Get detailed information about a mode's gate behavior.
        
        Args:
            mode: Execution mode name
            
        Returns:
            Dict with mode information
        """
        sensitivity = self.get_sensitivity(mode)
        
        return {
            "mode": mode,
            "sensitivity": sensitivity.to_dict(),
            "description": self._get_mode_description(mode),
            "use_cases": self._get_mode_use_cases(mode)
        }
    
    def _get_mode_description(self, mode: str) -> str:
        """Get human-readable description for a mode."""
        descriptions = {
            "deterministic": (
                "Strictest mode for production and critical operations. "
                "Fails on any unresolved gap. No advisory pass or confidence override. "
                "Recommended for automated pipelines and high-stakes operations."
            ),
            "guided_autonomy": (
                "Moderate strictness for assisted operations. "
                "Allows limited SEV-2 gaps and advisory pass with HIGH confidence. "
                "Recommended for semi-automated workflows with human oversight."
            ),
            "fast_prototype": (
                "Most lenient mode for rapid iteration and prototyping. "
                "Allows more gaps and unsafe operations. "
                "Recommended for development, testing, and experimentation."
            ),
            "direct": (
                "Default mode with balanced strictness. "
                "Standard gate evaluation with moderate thresholds. "
                "Suitable for general-purpose operations."
            )
        }
        return descriptions.get(mode, "Custom mode with user-defined sensitivity.")
    
    def _get_mode_use_cases(self, mode: str) -> List[str]:
        """Get recommended use cases for a mode."""
        use_cases = {
            "deterministic": [
                "Production deployments",
                "Automated CI/CD pipelines",
                "Critical system changes",
                "Regulatory compliance workflows"
            ],
            "guided_autonomy": [
                "Code review assistance",
                "Documentation generation",
                "Semi-automated refactoring",
                "Quality gate enforcement"
            ],
            "fast_prototype": [
                "Rapid prototyping",
                "Proof of concept development",
                "Testing and experimentation",
                "Learning and exploration"
            ],
            "direct": [
                "General development",
                "Standard operations",
                "Interactive sessions",
                "Default workflows"
            ]
        }
        return use_cases.get(mode, ["Custom use cases"])
    
    def list_modes(self) -> List[str]:
        """List all available modes."""
        return list(self._sensitivity_configs.keys())
    
    def validate_mode_config(self, mode: str) -> List[str]:
        """
        Validate configuration for a mode.
        
        Args:
            mode: Mode name to validate
            
        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        sensitivity = self.get_sensitivity(mode)
        
        # SEV-1 should always have max 0
        if sensitivity.max_sev1_gaps > 0:
            errors.append(
                f"max_sev1_gaps should be 0 (got {sensitivity.max_sev1_gaps}). "
                "SEV-1 gaps should always block."
            )
        
        # Warn threshold should be reasonable
        if sensitivity.warn_threshold_pct < 0 or sensitivity.warn_threshold_pct > 100:
            errors.append(
                f"warn_threshold_pct should be 0-100 (got {sensitivity.warn_threshold_pct})"
            )
        
        # Confidence override should not be enabled with fail_on_any_gap
        if sensitivity.confidence_override and sensitivity.fail_on_any_gap:
            errors.append(
                "confidence_override=True conflicts with fail_on_any_gap=True. "
                "Confidence override is ineffective when fail_on_any_gap is set."
            )
        
        # Unsafe mode should have appropriate warnings logged
        if sensitivity.allow_unsafe and mode == "deterministic":
            errors.append(
                "allow_unsafe=True is not recommended for deterministic mode. "
                "This may compromise safety guarantees."
            )
        
        return errors


def get_gate_behavior_modifier(config: Dict[str, Any] = None) -> GateBehaviorModifier:
    """
    Factory function to create a GateBehaviorModifier.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        GateBehaviorModifier instance
    """
    return GateBehaviorModifier(config)


def apply_gate_mode_rules(result: GateResult, 
                          mode: str,
                          gaps: List[Dict[str, Any]] = None,
                          confidence: str = "MEDIUM",
                          config: Dict[str, Any] = None) -> ModifiedGateResult:
    """
    Convenience function to apply mode rules to a gate result.
    
    Args:
        result: Original gate result
        mode: Execution mode
        gaps: List of gap dictionaries
        confidence: Current confidence level
        config: Configuration dictionary
        
    Returns:
        ModifiedGateResult with potentially modified result
    """
    modifier = GateBehaviorModifier(config)
    return modifier.apply_mode_rules(result, mode, gaps, confidence)
