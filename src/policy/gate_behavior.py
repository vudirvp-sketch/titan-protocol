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

# [ITEM-GATE-001] Mode-aware gate behavior imports


class ExecutionMode(Enum):
    """
    Execution modes with different gate sensitivity.
    
    [ITEM-GATE-001] Extended with CI/CD and multi-agent modes.
    
    Mode Hierarchy (strictness descending):
    1. CI_CD_PIPELINE - Strictest, fail-fast, production CI/CD
    2. DETERMINISTIC - Production/critical operations
    3. MULTI_AGENT_SWARM - Consensus-based, strict
    4. GUIDED_AUTONOMY - Moderate strictness, assisted operations
    5. SINGLE_LLM_EXECUTOR - Balanced, retry-generous
    6. DIRECT - Default mode, standard operations
    7. FAST_PROTOTYPE - Most lenient, rapid iteration
    """
    # [ITEM-GATE-001] New modes for v5.0.0
    CI_CD_PIPELINE = "ci_cd_pipeline"
    SINGLE_LLM_EXECUTOR = "single_llm_executor"
    MULTI_AGENT_SWARM = "multi_agent_swarm"
    
    # Existing modes
    DETERMINISTIC = "deterministic"
    GUIDED_AUTONOMY = "guided_autonomy"
    FAST_PROTOTYPE = "fast_prototype"
    DIRECT = "direct"  # Default mode


@dataclass
class ModeProfile:
    """
    [ITEM-GATE-001] Mode profile with sensitivity multiplier.
    
    Defines behavior characteristics for each execution mode.
    
    Attributes:
        mode: The execution mode this profile describes
        strict_mode: Whether to use strict validation
        fail_fast: Whether to fail immediately on any violation
        sensitivity_multiplier: Multiplier applied to gate thresholds (0.8 = stricter)
        retry_generous: Whether to allow generous retries
        consensus_required: Whether multi-agent consensus is required
        max_retries: Maximum number of retries allowed
        description: Human-readable description of the mode
    """
    mode: 'ExecutionMode'
    strict_mode: bool
    fail_fast: bool
    sensitivity_multiplier: float
    retry_generous: bool = False
    consensus_required: bool = False
    max_retries: int = 3
    description: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode.value,
            "strict_mode": self.strict_mode,
            "fail_fast": self.fail_fast,
            "sensitivity_multiplier": self.sensitivity_multiplier,
            "retry_generous": self.retry_generous,
            "consensus_required": self.consensus_required,
            "max_retries": self.max_retries,
            "description": self.description
        }


# [ITEM-GATE-001] Mode profiles as defined in protocol
MODE_PROFILES: Dict[ExecutionMode, ModeProfile] = {
    ExecutionMode.CI_CD_PIPELINE: ModeProfile(
        mode=ExecutionMode.CI_CD_PIPELINE,
        strict_mode=True,
        fail_fast=True,
        sensitivity_multiplier=0.8,
        retry_generous=False,
        consensus_required=False,
        max_retries=1,
        description="Production CI/CD - strictest settings, fail-fast on any violation"
    ),
    ExecutionMode.SINGLE_LLM_EXECUTOR: ModeProfile(
        mode=ExecutionMode.SINGLE_LLM_EXECUTOR,
        strict_mode=False,
        fail_fast=False,
        sensitivity_multiplier=1.0,
        retry_generous=True,
        consensus_required=False,
        max_retries=5,
        description="Single LLM - balanced settings, generous retries"
    ),
    ExecutionMode.MULTI_AGENT_SWARM: ModeProfile(
        mode=ExecutionMode.MULTI_AGENT_SWARM,
        strict_mode=True,
        fail_fast=False,
        sensitivity_multiplier=0.9,
        retry_generous=False,
        consensus_required=True,
        max_retries=3,
        description="Multi-agent - consensus-based, strict validation"
    ),
    ExecutionMode.DETERMINISTIC: ModeProfile(
        mode=ExecutionMode.DETERMINISTIC,
        strict_mode=True,
        fail_fast=True,
        sensitivity_multiplier=0.85,
        retry_generous=False,
        consensus_required=False,
        max_retries=2,
        description="Deterministic - production/critical operations, fail on any gap"
    ),
    ExecutionMode.GUIDED_AUTONOMY: ModeProfile(
        mode=ExecutionMode.GUIDED_AUTONOMY,
        strict_mode=False,
        fail_fast=False,
        sensitivity_multiplier=1.0,
        retry_generous=True,
        consensus_required=False,
        max_retries=4,
        description="Guided autonomy - moderate strictness, assisted operations"
    ),
    ExecutionMode.FAST_PROTOTYPE: ModeProfile(
        mode=ExecutionMode.FAST_PROTOTYPE,
        strict_mode=False,
        fail_fast=False,
        sensitivity_multiplier=1.2,
        retry_generous=True,
        consensus_required=False,
        max_retries=10,
        description="Fast prototype - most lenient, rapid iteration"
    ),
    ExecutionMode.DIRECT: ModeProfile(
        mode=ExecutionMode.DIRECT,
        strict_mode=False,
        fail_fast=False,
        sensitivity_multiplier=1.0,
        retry_generous=False,
        consensus_required=False,
        max_retries=3,
        description="Direct - default mode, standard operations"
    ),
}


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
    # [ITEM-GATE-001] New modes for v5.0.0
    "ci_cd_pipeline": GateSensitivityConfig(
        fail_on_any_gap=True,
        warn_threshold_pct=3.0,
        max_sev1_gaps=0,
        max_sev2_gaps=0,
        max_sev3_gaps=0,
        max_sev4_gaps=0,
        allow_advisory_pass=False,
        allow_unsafe=False,
        confidence_override=False
    ),
    "single_llm_executor": GateSensitivityConfig(
        fail_on_any_gap=False,
        warn_threshold_pct=15.0,
        max_sev1_gaps=0,
        max_sev2_gaps=3,
        max_sev3_gaps=8,
        max_sev4_gaps=15,
        allow_advisory_pass=True,
        allow_unsafe=False,
        confidence_override=True
    ),
    "multi_agent_swarm": GateSensitivityConfig(
        fail_on_any_gap=False,
        warn_threshold_pct=10.0,
        max_sev1_gaps=0,
        max_sev2_gaps=1,
        max_sev3_gaps=5,
        max_sev4_gaps=10,
        allow_advisory_pass=True,
        allow_unsafe=False,
        confidence_override=False
    ),
    # Existing modes
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
    ITEM-GATE-001: Mode-aware gate behavior with sensitivity multiplier.
    
    This class applies mode-specific sensitivity settings to gate
    evaluation results, allowing different strictness levels for
    different use cases.
    
    Mode Behaviors:
    
    **ci_cd_pipeline** [ITEM-GATE-001]:
    - Strictest mode for production CI/CD pipelines
    - fail_fast=True, immediate failure on any violation
    - sensitivity_multiplier=0.8 (stricter thresholds)
    - Single retry only
    
    **single_llm_executor** [ITEM-GATE-001]:
    - Balanced mode for single LLM execution
    - retry_generous=True, multiple attempts allowed
    - sensitivity_multiplier=1.0 (default thresholds)
    
    **multi_agent_swarm** [ITEM-GATE-001]:
    - Consensus-based mode for multi-agent systems
    - consensus_required=True
    - sensitivity_multiplier=0.9
    
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
        # [ITEM-GATE-001] New mode-aware initialization
        modifier = GateBehaviorModifier(mode=ExecutionMode.CI_CD_PIPELINE, config=config)
        
        # Get mode profile
        profile = modifier.get_mode_profile()
        
        # Apply sensitivity multiplier to thresholds
        adjusted = modifier.apply_sensitivity(thresholds)
        
        # Check if should fail fast
        if modifier.should_fail_fast("SEV-2"):
            return GateResult.FAIL
    """
    
    def __init__(self, mode: ExecutionMode = None, config: Dict[str, Any] = None):
        """
        Initialize gate behavior modifier.
        
        [ITEM-GATE-001] Enhanced with mode parameter.
        
        Args:
            mode: Execution mode (optional, for mode-aware behavior)
            config: Configuration dictionary with mode-specific settings
        """
        self.config = config or {}
        self._logger = logging.getLogger(__name__)
        
        # [ITEM-GATE-001] Store execution mode
        self._mode = mode or ExecutionMode.DIRECT
        self._profile = self._load_mode_profile()
        
        # Load sensitivity configurations
        self._sensitivity_configs = self._load_sensitivity_configs()
    
    def _load_mode_profile(self) -> ModeProfile:
        """[ITEM-GATE-001] Load mode profile from MODE_PROFILES."""
        if self._mode in MODE_PROFILES:
            return MODE_PROFILES[self._mode]
        
        # Fallback to DIRECT profile
        self._logger.warning(
            f"[ITEM-GATE-001] No profile for mode '{self._mode}', using DIRECT"
        )
        return MODE_PROFILES[ExecutionMode.DIRECT]
    
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
        
        # [ITEM-GATE-001] Extended mode aliases for new modes
        mode_aliases = {
            "guided_autonomy": "guided_autonomy",
            "guided autonomy": "guided_autonomy",
            "fast_prototype": "fast_prototype",
            "fast prototype": "fast_prototype",
            "fast": "fast_prototype",
            "proto": "fast_prototype",
            # [ITEM-GATE-001] New mode aliases
            "ci_cd_pipeline": "ci_cd_pipeline",
            "ci-cd": "ci_cd_pipeline",
            "ci_cd": "ci_cd_pipeline",
            "cicd": "ci_cd_pipeline",
            "single_llm_executor": "single_llm_executor",
            "single_llm": "single_llm_executor",
            "single": "single_llm_executor",
            "multi_agent_swarm": "multi_agent_swarm",
            "multi_agent": "multi_agent_swarm",
            "swarm": "multi_agent_swarm",
        }
        
        mode_key = mode_aliases.get(mode_normalized, mode_normalized)
        
        if mode_key not in self._sensitivity_configs:
            self._logger.warning(
                f"[ITEM-GATE-001] Unknown mode '{mode}', using 'direct' as default"
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
    
    # [ITEM-GATE-001] New mode-aware methods
    
    def get_mode_profile(self) -> ModeProfile:
        """
        Get the current mode profile.
        
        [ITEM-GATE-001] Returns the ModeProfile for the configured execution mode.
        
        Returns:
            ModeProfile for the current mode
        """
        self._logger.debug(
            f"[ITEM-GATE-001] Getting profile for mode '{self._mode.value}'"
        )
        return self._profile
    
    def apply_sensitivity(self, thresholds: Dict[str, float]) -> Dict[str, float]:
        """
        Apply sensitivity_multiplier to thresholds.
        
        [ITEM-GATE-001] Adjusts gate thresholds based on mode sensitivity.
        Lower multiplier = stricter thresholds.
        
        Args:
            thresholds: Dict of threshold names to values
            
        Returns:
            Dict with adjusted threshold values
            
        Example:
            >>> modifier = GateBehaviorModifier(ExecutionMode.CI_CD_PIPELINE)
            >>> modifier.apply_sensitivity({"max_sev2": 10})
            {"max_sev2": 8.0}  # 10 * 0.8 = 8.0
        """
        adjusted = {}
        multiplier = self._profile.sensitivity_multiplier
        
        for key, value in thresholds.items():
            if isinstance(value, (int, float)):
                adjusted[key] = value * multiplier
            else:
                adjusted[key] = value
        
        self._logger.debug(
            f"[ITEM-GATE-001] Applied sensitivity multiplier {multiplier} "
            f"to {len(thresholds)} thresholds for mode '{self._mode.value}'"
        )
        
        return adjusted
    
    def should_fail_fast(self, error_severity: str) -> bool:
        """
        Determine if error should cause immediate failure.
        
        [ITEM-GATE-001] Checks if the mode's fail_fast setting should
        trigger immediate termination for the given error severity.
        
        Args:
            error_severity: Severity of the error (SEV-1, SEV-2, SEV-3, SEV-4)
            
        Returns:
            True if should fail immediately, False otherwise
            
        Rules:
            - SEV-1 always causes fail_fast (regardless of mode)
            - fail_fast=True modes fail on any severity
            - fail_fast=False modes only fail on SEV-1
        """
        # SEV-1 always causes immediate failure
        if error_severity == "SEV-1":
            return True
        
        # Check mode's fail_fast setting
        should_fail = self._profile.fail_fast
        
        if should_fail:
            self._logger.info(
                f"[ITEM-GATE-001] Mode '{self._mode.value}' failing fast on "
                f"{error_severity} (fail_fast=True)"
            )
        else:
            self._logger.debug(
                f"[ITEM-GATE-001] Mode '{self._mode.value}' NOT failing fast on "
                f"{error_severity} (fail_fast=False)"
            )
        
        return should_fail
    
    def get_retry_count(self) -> int:
        """
        Get max retries based on mode.
        
        [ITEM-GATE-001] Returns the maximum number of retries allowed
        for the current execution mode.
        
        Returns:
            Maximum number of retries allowed
            
        Mode defaults:
            - CI_CD_PIPELINE: 1 (minimal retries)
            - SINGLE_LLM_EXECUTOR: 5 (generous retries)
            - MULTI_AGENT_SWARM: 3 (standard)
            - DETERMINISTIC: 2 (limited)
            - GUIDED_AUTONOMY: 4 (moderate)
            - FAST_PROTOTYPE: 10 (very generous)
            - DIRECT: 3 (standard)
        """
        retries = self._profile.max_retries
        
        # Check if retry_generous is enabled - may add bonus retries
        if self._profile.retry_generous:
            retries = max(retries, 3)  # At least 3 retries when generous
        
        self._logger.debug(
            f"[ITEM-GATE-001] Mode '{self._mode.value}' allows {retries} retries "
            f"(retry_generous={self._profile.retry_generous})"
        )
        
        return retries
    
    def requires_consensus(self) -> bool:
        """
        Check if consensus is required for this mode.
        
        [ITEM-GATE-001] Determines whether multi-agent consensus is
        required before proceeding with gate decisions.
        
        Returns:
            True if consensus is required, False otherwise
            
        Use cases:
            - MULTI_AGENT_SWARM requires consensus
            - Other modes do not require consensus
        """
        required = self._profile.consensus_required
        
        if required:
            self._logger.info(
                f"[ITEM-GATE-001] Mode '{self._mode.value}' requires consensus "
                f"for gate decisions"
            )
        
        return required
    
    def is_strict_mode(self) -> bool:
        """
        Check if strict mode is enabled.
        
        [ITEM-GATE-001] Returns whether the current mode uses strict
        validation rules.
        
        Returns:
            True if strict mode is enabled
        """
        return self._profile.strict_mode
    
    def get_current_mode(self) -> ExecutionMode:
        """
        Get the current execution mode.
        
        [ITEM-GATE-001] Returns the ExecutionMode enum value for this modifier.
        
        Returns:
            Current ExecutionMode
        """
        return self._mode


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
