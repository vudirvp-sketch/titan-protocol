"""
Guardian Validation Loop for TITAN FUSE Protocol.

ITEM-VAL-03: Deterministic validation loop integrating scoring engine,
conflict resolver, and SCOUT pipeline for comprehensive content validation.

ITEM-PROT-001: Hyperparameter Enforcement Gate for deterministic mode validation.
Enforces temperature=0.0, top_p<=0.1, and seed as strict integer in DETERMINISM=strict mode.

The Guardian serves as the central orchestrator for validation, combining:
- Adaptive Weight Profiles Engine for four-axis scoring
- Conflict Resolution Formula for idea-level conflicts
- SCOUT Pipeline for multi-agent analysis
- Hyperparameter Validation for deterministic LLM calls

Author: TITAN FUSE Team
Version: 5.0.0
"""

from __future__ import annotations

import logging
import copy
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Callable

# Import from scoring module
from src.scoring.adaptive_weights import (
    AdaptiveWeightEngine,
    WeightProfile,
    WeightedScore,
    Decision as ScoringDecision,
    ConflictResolution as WeightConflictResolution,
)

# Import from decision module
from src.decision.conflict_resolver import (
    ConflictResolver,
    ConflictMetrics,
    Decision as ConflictDecision,
    DecisionConfidence,
)

# Import from agents module
from src.agents.scout_matrix import (
    ScoutPipeline,
    ScoutOutput,
    AnalysisContext,
    PipelineContext,
    AdoptionReadiness,
    AgentRole,
)

# Import validation result from existing module
from .validator_dag import ValidationResult

# Configure module logger
logger = logging.getLogger(__name__)


# =============================================================================
# ITEM-PROT-001: Hyperparameter Enforcement Gate
# =============================================================================

class EnforcementMode(Enum):
    """
    Hyperparameter enforcement mode.

    Attributes:
        STRICT: Strict enforcement, reject on any violation
        RELAXED: Relaxed enforcement, warn on violations
    """
    STRICT = "strict"
    RELAXED = "relaxed"


class ViolationAction(Enum):
    """
    Action to take on hyperparameter violation.

    Attributes:
        REJECT: Reject the request entirely
        WARN: Log warning but allow the request
        AUTO_FIX: Automatically fix parameters and continue
    """
    REJECT = "reject"
    WARN = "warn"
    AUTO_FIX = "auto_fix"


@dataclass
class HyperparameterConfig:
    """
    Configuration for hyperparameter enforcement.

    Attributes:
        enforcement: Enforcement mode (strict or relaxed)
        on_violation: Action to take on violation
        allowed_temperature: Allowed temperature value in strict mode
        max_top_p: Maximum allowed top_p in strict mode
        require_seed: Whether seed is required
    """
    enforcement: EnforcementMode = EnforcementMode.STRICT
    on_violation: ViolationAction = ViolationAction.REJECT
    allowed_temperature: float = 0.0
    max_top_p: float = 0.1
    require_seed: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "enforcement": self.enforcement.value,
            "on_violation": self.on_violation.value,
            "allowed_temperature": self.allowed_temperature,
            "max_top_p": self.max_top_p,
            "require_seed": self.require_seed,
        }


@dataclass
class HyperparameterViolation:
    """
    Represents a hyperparameter violation detected during validation.

    Attributes:
        param_name: Name of the violated parameter
        expected: Expected value or range
        actual: Actual value provided
        severity: Severity level (1-5)
        message: Human-readable description
        auto_fix_value: Value to use if auto-fix is enabled
    """
    param_name: str
    expected: str
    actual: Any
    severity: int
    message: str
    auto_fix_value: Any = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "param_name": self.param_name,
            "expected": self.expected,
            "actual": self.actual,
            "severity": self.severity,
            "message": self.message,
            "auto_fix_value": self.auto_fix_value,
        }


@dataclass
class HyperparameterValidationResult:
    """
    Result of hyperparameter validation.

    Attributes:
        valid: Whether parameters are valid
        violations: List of detected violations
        fixed_params: Auto-fixed parameters if applicable
        was_auto_fixed: Whether parameters were auto-fixed
    """
    valid: bool
    violations: List[HyperparameterViolation] = field(default_factory=list)
    fixed_params: Dict[str, Any] = field(default_factory=dict)
    was_auto_fixed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "valid": self.valid,
            "violations": [v.to_dict() for v in self.violations],
            "fixed_params": self.fixed_params,
            "was_auto_fixed": self.was_auto_fixed,
        }


class HyperparameterValidator:
    """
    ITEM-PROT-001: Hyperparameter Enforcement Gate for TITAN Protocol.

    Validates and enforces hyperparameters for deterministic LLM calls.
    When DETERMINISM=strict mode is enabled, enforces:
    - temperature ∈ {0.0}
    - top_p ≤ 0.1
    - seed is strict integer

    The validator integrates with the Gate Manager to block requests
    that don't meet deterministic requirements.

    Usage:
        >>> config = HyperparameterConfig(
        ...     enforcement=EnforcementMode.STRICT,
        ...     on_violation=ViolationAction.AUTO_FIX
        ... )
        >>> validator = HyperparameterValidator(config)
        >>>
        >>> # Validate parameters
        >>> params = {"temperature": 0.7, "top_p": 0.9, "seed": 42}
        >>> result = validator.validate_deterministic(params)
        >>>
        >>> if result.was_auto_fixed:
        ...     params = result.fixed_params
        >>> elif not result.valid:
        ...     raise ValueError("Invalid hyperparameters")

    Integration with GateManager:
        The validator should be registered as a check function for the
        "Hyperparameter Check" gate in GATE_00.
    """

    # Default values for strict determinism
    DEFAULT_STRICT_TEMPERATURE = 0.0
    DEFAULT_STRICT_TOP_P = 0.1

    def __init__(self, config: Optional[HyperparameterConfig] = None) -> None:
        """
        Initialize the HyperparameterValidator.

        Args:
            config: Configuration for hyperparameter enforcement.
                   If not provided, uses defaults (strict mode, reject on violation).
        """
        self._config = config or HyperparameterConfig()
        self._logger = logging.getLogger(f"{__name__}.HyperparameterValidator")

        # Track validation statistics
        self._stats = {
            "total_validations": 0,
            "valid_count": 0,
            "violation_count": 0,
            "auto_fix_count": 0,
            "reject_count": 0,
            "warn_count": 0,
        }

        self._logger.info(
            f"[ITEM-PROT-001] HyperparameterValidator initialized: "
            f"enforcement={self._config.enforcement.value}, "
            f"on_violation={self._config.on_violation.value}"
        )

    def validate_deterministic(self, params: Dict[str, Any]) -> HyperparameterValidationResult:
        """
        Validate parameters for deterministic mode.

        Checks all hyperparameters against strict mode requirements:
        - temperature must be exactly 0.0
        - top_p must be ≤ 0.1
        - seed must be an integer

        Args:
            params: LLM call parameters to validate

        Returns:
            HyperparameterValidationResult with validation outcome
        """
        self._stats["total_validations"] += 1
        violations: List[HyperparameterViolation] = []
        fixed_params = copy.deepcopy(params) if self._config.on_violation == ViolationAction.AUTO_FIX else {}
        was_auto_fixed = False

        # Check temperature
        temp_violation = self._check_temperature(params)
        if temp_violation:
            violations.append(temp_violation)
            if self._config.on_violation == ViolationAction.AUTO_FIX:
                fixed_params["temperature"] = temp_violation.auto_fix_value
                was_auto_fixed = True

        # Check top_p
        top_p_violation = self._check_top_p(params)
        if top_p_violation:
            violations.append(top_p_violation)
            if self._config.on_violation == ViolationAction.AUTO_FIX:
                fixed_params["top_p"] = top_p_violation.auto_fix_value
                was_auto_fixed = True

        # Check seed
        seed_violation = self._check_seed(params)
        if seed_violation:
            violations.append(seed_violation)
            if self._config.on_violation == ViolationAction.AUTO_FIX and seed_violation.auto_fix_value is not None:
                fixed_params["seed"] = seed_violation.auto_fix_value
                was_auto_fixed = True

        # Determine validity and handle actions
        if not violations:
            self._stats["valid_count"] += 1
            return HyperparameterValidationResult(valid=True)

        self._stats["violation_count"] += 1

        # Handle violation based on configured action
        if self._config.on_violation == ViolationAction.AUTO_FIX:
            # Check if all violations can be fixed
            unfixable = [v for v in violations if v.auto_fix_value is None]
            if unfixable:
                self._stats["reject_count"] += 1
                self._logger.error(
                    f"[ITEM-PROT-001] Cannot auto-fix {len(unfixable)} violations: "
                    f"{[v.param_name for v in unfixable]}"
                )
                return HyperparameterValidationResult(
                    valid=False,
                    violations=violations,
                    fixed_params={},
                    was_auto_fixed=False,
                )

            self._stats["auto_fix_count"] += 1
            # Merge fixed params with original
            result_params = copy.deepcopy(params)
            result_params.update(fixed_params)

            self._logger.info(
                f"[ITEM-PROT-001] Auto-fixed {len(violations)} hyperparameter violations: "
                f"{[v.param_name for v in violations]}"
            )

            return HyperparameterValidationResult(
                valid=True,
                violations=violations,
                fixed_params=result_params,
                was_auto_fixed=True,
            )

        elif self._config.on_violation == ViolationAction.WARN:
            self._stats["warn_count"] += 1
            self._logger.warning(
                f"[ITEM-PROT-001] Hyperparameter violations detected (warn mode): "
                f"{[v.message for v in violations]}"
            )
            return HyperparameterValidationResult(valid=True, violations=violations)

        else:  # REJECT
            self._stats["reject_count"] += 1
            self._logger.error(
                f"[ITEM-PROT-001] Hyperparameter validation rejected: "
                f"{[v.message for v in violations]}"
            )
            return HyperparameterValidationResult(valid=False, violations=violations)

    def check_temperature(self, value: float) -> bool:
        """
        Check if temperature value is valid for deterministic mode.

        Args:
            value: Temperature value to check

        Returns:
            True if temperature is valid (0.0 in strict mode)
        """
        if self._config.enforcement == EnforcementMode.STRICT:
            return value == self._config.allowed_temperature
        return True  # Relaxed mode allows any temperature

    def _check_temperature(self, params: Dict[str, Any]) -> Optional[HyperparameterViolation]:
        """
        Internal method to check temperature parameter.

        Args:
            params: Parameters dictionary

        Returns:
            HyperparameterViolation if invalid, None if valid
        """
        if "temperature" not in params:
            # Missing temperature - not a violation, will be set by seed injector
            return None

        temp = params["temperature"]

        if self._config.enforcement == EnforcementMode.STRICT:
            if temp != self._config.allowed_temperature:
                return HyperparameterViolation(
                    param_name="temperature",
                    expected=f"{self._config.allowed_temperature}",
                    actual=temp,
                    severity=5,
                    message=f"Temperature must be {self._config.allowed_temperature} in strict mode, got {temp}",
                    auto_fix_value=self.DEFAULT_STRICT_TEMPERATURE,
                )

        return None

    def check_top_p(self, value: float) -> bool:
        """
        Check if top_p value is valid for deterministic mode.

        Args:
            value: top_p value to check

        Returns:
            True if top_p is valid (≤ 0.1 in strict mode)
        """
        if self._config.enforcement == EnforcementMode.STRICT:
            return value <= self._config.max_top_p
        return True  # Relaxed mode allows any top_p

    def _check_top_p(self, params: Dict[str, Any]) -> Optional[HyperparameterViolation]:
        """
        Internal method to check top_p parameter.

        Args:
            params: Parameters dictionary

        Returns:
            HyperparameterViolation if invalid, None if valid
        """
        if "top_p" not in params:
            # Missing top_p - not a violation
            return None

        top_p = params["top_p"]

        if self._config.enforcement == EnforcementMode.STRICT:
            if top_p > self._config.max_top_p:
                return HyperparameterViolation(
                    param_name="top_p",
                    expected=f"≤{self._config.max_top_p}",
                    actual=top_p,
                    severity=4,
                    message=f"top_p must be ≤ {self._config.max_top_p} in strict mode, got {top_p}",
                    auto_fix_value=self.DEFAULT_STRICT_TOP_P,
                )

        return None

    def check_seed(self, value: Any) -> bool:
        """
        Check if seed value is valid for deterministic mode.

        Args:
            value: Seed value to check

        Returns:
            True if seed is a valid integer
        """
        if not self._config.require_seed:
            return True

        # Must be an integer (int type, not float or string)
        if isinstance(value, bool):  # bool is subclass of int, reject it
            return False
        if isinstance(value, int):
            return True
        return False

    def _check_seed(self, params: Dict[str, Any]) -> Optional[HyperparameterViolation]:
        """
        Internal method to check seed parameter.

        Args:
            params: Parameters dictionary

        Returns:
            HyperparameterViolation if invalid, None if valid
        """
        if not self._config.require_seed:
            return None

        if "seed" not in params:
            return HyperparameterViolation(
                param_name="seed",
                expected="integer",
                actual=None,
                severity=5,
                message="Seed is required for deterministic mode",
                auto_fix_value=None,  # Cannot auto-fix missing seed
            )

        seed = params["seed"]

        # Check if it's a proper integer (not bool, not float, not string)
        if isinstance(seed, bool):
            return HyperparameterViolation(
                param_name="seed",
                expected="integer",
                actual=seed,
                severity=5,
                message=f"Seed must be an integer, got boolean {seed}",
                auto_fix_value=int(seed),
            )

        if not isinstance(seed, int):
            # Try to convert if auto-fix enabled
            try:
                converted = int(seed)
                return HyperparameterViolation(
                    param_name="seed",
                    expected="integer",
                    actual=seed,
                    severity=5,
                    message=f"Seed must be an integer, got {type(seed).__name__}: {seed}",
                    auto_fix_value=converted,
                )
            except (ValueError, TypeError):
                return HyperparameterViolation(
                    param_name="seed",
                    expected="integer",
                    actual=seed,
                    severity=5,
                    message=f"Seed must be an integer, got invalid value: {seed}",
                    auto_fix_value=None,
                )

        return None

    def auto_fix(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Auto-correct parameters for deterministic mode.

        Applies fixes for any parameter violations:
        - Sets temperature to 0.0
        - Sets top_p to 0.1
        - Converts seed to integer if possible

        Args:
            params: Original parameters

        Returns:
            Corrected parameters dictionary
        """
        result = copy.deepcopy(params)

        # Fix temperature
        if "temperature" in result and result["temperature"] != self.DEFAULT_STRICT_TEMPERATURE:
            self._logger.debug(
                f"[ITEM-PROT-001] Auto-fixing temperature: "
                f"{result['temperature']} -> {self.DEFAULT_STRICT_TEMPERATURE}"
            )
            result["temperature"] = self.DEFAULT_STRICT_TEMPERATURE

        # Fix top_p
        if "top_p" in result and result["top_p"] > self.DEFAULT_STRICT_TOP_P:
            self._logger.debug(
                f"[ITEM-PROT-001] Auto-fixing top_p: "
                f"{result['top_p']} -> {self.DEFAULT_STRICT_TOP_P}"
            )
            result["top_p"] = self.DEFAULT_STRICT_TOP_P

        # Fix seed
        if "seed" in result:
            seed = result["seed"]
            if isinstance(seed, bool):
                result["seed"] = int(seed)
            elif not isinstance(seed, int):
                try:
                    result["seed"] = int(seed)
                    self._logger.debug(
                        f"[ITEM-PROT-001] Auto-fixing seed: {seed} -> {result['seed']}"
                    )
                except (ValueError, TypeError):
                    self._logger.warning(
                        f"[ITEM-PROT-001] Cannot auto-fix seed: {seed}"
                    )

        return result

    def get_stats(self) -> Dict[str, int]:
        """
        Get validation statistics.

        Returns:
            Dictionary with validation counts
        """
        return self._stats.copy()

    def reset_stats(self) -> None:
        """Reset validation statistics."""
        self._stats = {
            "total_validations": 0,
            "valid_count": 0,
            "violation_count": 0,
            "auto_fix_count": 0,
            "reject_count": 0,
            "warn_count": 0,
        }

    @property
    def config(self) -> HyperparameterConfig:
        """Get the current configuration."""
        return self._config

    def update_config(self, config: HyperparameterConfig) -> None:
        """
        Update the validator configuration.

        Args:
            config: New configuration
        """
        self._config = config
        self._logger.info(
            f"[ITEM-PROT-001] Configuration updated: "
            f"enforcement={config.enforcement.value}, on_violation={config.on_violation.value}"
        )


def create_hyperparameter_validator(
    enforcement: str = "strict",
    on_violation: str = "reject"
) -> HyperparameterValidator:
    """
    Factory function to create a HyperparameterValidator.

    Args:
        enforcement: Enforcement mode ("strict" or "relaxed")
        on_violation: Action on violation ("reject", "warn", or "auto_fix")

    Returns:
        Configured HyperparameterValidator instance
    """
    config = HyperparameterConfig(
        enforcement=EnforcementMode(enforcement),
        on_violation=ViolationAction(on_violation),
    )
    return HyperparameterValidator(config)


# =============================================================================
# Enums
# =============================================================================

class ValidationMode(Enum):
    """
    Validation execution modes.

    Attributes:
        STANDARD: Normal validation with all checks
        FAST: Quick validation, skip optional agents
        THOROUGH: Deep validation with extended analysis
        STRICT: Strict mode, fail on any warning
    """
    STANDARD = "standard"
    FAST = "fast"
    THOROUGH = "thorough"
    STRICT = "strict"


class ConflictType(Enum):
    """
    Types of conflicts that can be detected during validation.

    Attributes:
        SCORE_MISMATCH: Discrepancy between expected and actual scores
        DOMAIN_VOLATILITY: High volatility domain with low confidence
        HYPE_DETECTED: Marketing hype indicators found
        RISK_FLAG: Risk factors identified by DEVIL agent
        READINESS_BLOCKER: Readiness tier blocks proceeding
        VETO_TRIGGERED: EVAL agent vetoed strategy synthesis
        POLICY_VIOLATION: Content violates validation policies
        DEPENDENCY_CONFLICT: Conflicting dependencies detected
    """
    SCORE_MISMATCH = "score_mismatch"
    DOMAIN_VOLATILITY = "domain_volatility"
    HYPE_DETECTED = "hype_detected"
    RISK_FLAG = "risk_flag"
    READINESS_BLOCKER = "readiness_blocker"
    VETO_TRIGGERED = "veto_triggered"
    POLICY_VIOLATION = "policy_violation"
    DEPENDENCY_CONFLICT = "dependency_conflict"


class ResolutionStatus(Enum):
    """
    Status of conflict resolution.

    Attributes:
        RESOLVED: Conflict successfully resolved
        ESCALATED: Conflict escalated for human review
        BLOCKED: Resolution blocked, cannot proceed
        DEFERRED: Resolution deferred pending additional data
    """
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    BLOCKED = "blocked"
    DEFERRED = "deferred"


# =============================================================================
# Dataclasses
# =============================================================================

@dataclass
class Conflict:
    """
    Represents a detected conflict during validation.

    Attributes:
        conflict_type: Type of conflict detected
        severity: Severity level (1-5, 5 being most severe)
        description: Human-readable description
        source: Source component that detected the conflict
        context: Additional context data
        timestamp: When the conflict was detected
        resolution_hint: Suggested resolution approach
    """
    conflict_type: ConflictType
    severity: int
    description: str
    source: str
    context: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    resolution_hint: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "conflict_type": self.conflict_type.value,
            "severity": self.severity,
            "description": self.description,
            "source": self.source,
            "context": self.context,
            "timestamp": self.timestamp,
            "resolution_hint": self.resolution_hint,
        }

    def is_critical(self) -> bool:
        """Check if conflict is critical (severity >= 4)."""
        return self.severity >= 4


@dataclass
class Resolution:
    """
    Represents a conflict resolution decision.

    Attributes:
        conflict: The original conflict that was resolved
        status: Resolution status
        action_taken: Action taken to resolve the conflict
        rationale: Explanation for the resolution decision
        confidence: Confidence in the resolution (0.0-1.0)
        alternatives: Alternative options that were considered
        timestamp: When the resolution was made
    """
    conflict: Conflict
    status: ResolutionStatus
    action_taken: str
    rationale: str
    confidence: float = 1.0
    alternatives: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "conflict": self.conflict.to_dict(),
            "status": self.status.value,
            "action_taken": self.action_taken,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "alternatives": self.alternatives,
            "timestamp": self.timestamp,
        }

    def is_successful(self) -> bool:
        """Check if resolution was successful."""
        return self.status == ResolutionStatus.RESOLVED


@dataclass
class GuardianResult:
    """
    Complete result from Guardian validation.

    Attributes:
        valid: Whether validation passed overall
        content_id: Identifier for the validated content
        mode: Validation mode used
        scout_output: Output from SCOUT pipeline
        conflicts: List of detected conflicts
        resolutions: List of applied resolutions
        scores: Weighted scores calculated during validation
        metadata: Additional validation metadata
        timestamp: When validation completed
        duration_ms: Validation duration in milliseconds
    """
    valid: bool
    content_id: str
    mode: ValidationMode
    scout_output: Optional[ScoutOutput] = None
    conflicts: List[Conflict] = field(default_factory=list)
    resolutions: List[Resolution] = field(default_factory=list)
    scores: Dict[str, WeightedScore] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "valid": self.valid,
            "content_id": self.content_id,
            "mode": self.mode.value,
            "scout_output": self.scout_output.to_dict() if self.scout_output else None,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "resolutions": [r.to_dict() for r in self.resolutions],
            "scores": {k: v.to_dict() for k, v in self.scores.items()},
            "metadata": self.metadata,
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
        }

    @property
    def has_conflicts(self) -> bool:
        """Check if any conflicts were detected."""
        return len(self.conflicts) > 0

    @property
    def has_critical_conflicts(self) -> bool:
        """Check if any critical conflicts exist."""
        return any(c.is_critical() for c in self.conflicts)

    @property
    def unresolved_count(self) -> int:
        """Count unresolved conflicts."""
        resolved_ids = {id(r.conflict) for r in self.resolutions if r.is_successful()}
        return sum(1 for c in self.conflicts if id(c) not in resolved_ids)


# =============================================================================
# Guardian Class
# =============================================================================

class Guardian:
    """
    Guardian Validation Loop for TITAN Protocol.

    Integrates the scoring engine, conflict resolver, and SCOUT pipeline
    into a deterministic validation loop that provides comprehensive
    content validation with conflict detection and resolution.

    The validation loop follows this process:
    1. Initialize components from configuration
    2. Run SCOUT pipeline for multi-agent analysis
    3. Calculate weighted scores using adaptive weights
    4. Detect conflicts from analysis results
    5. If conflicts detected, evaluate alternatives with weight engine
    6. Apply resolutions from conflict resolver
    7. Return comprehensive validation result

    Integration Points:
    - Apply adaptive weights on conflicts (WeightProfile)
    - Use conflict resolution formula (ConflictMetrics)
    - Log all decisions for audit trail

    Example:
        >>> config = {
        ...     "weight_profile": "TECHNICAL",
        ...     "strict_mode": True,
        ...     "conflict_weights": {"accuracy": 0.4, "utility": 0.35, ...}
        ... }
        >>> guardian = Guardian(config)
        >>> result = guardian.validate_content({
        ...     "subject": "New AI Framework",
        ...     "domain": "ai",
        ...     "claims": [...],
        ...     "evidence": [...]
        ... })
        >>> print(result.valid)
        True
    """

    # Default thresholds
    DEFAULT_SCORE_THRESHOLD = 7.0
    DEFAULT_CONFLICT_THRESHOLD = 0.6
    DEFAULT_HYPE_THRESHOLD = 0.5

    def __init__(self, config: Dict[str, Any]) -> None:
        """
        Initialize the Guardian validation loop.

        Args:
            config: Configuration dictionary with options:
                - weight_profile: Default weight profile name (default: "MIXED")
                - strict_mode: Enable strict validation mode (default: False)
                - conflict_weights: Custom conflict resolution weights
                - score_threshold: Minimum score threshold (default: 7.0)
                - include_radar: Include RADAR agent in pipeline (default: True)
                - custom_validators: List of custom validator functions

        Raises:
            ValueError: If configuration is invalid
        """
        self._config = config
        self._logger = logging.getLogger(f"{__name__}.Guardian")

        # Extract configuration options
        profile_name = config.get("weight_profile", "MIXED").upper()
        self._strict_mode = config.get("strict_mode", False)
        self._score_threshold = config.get("score_threshold", self.DEFAULT_SCORE_THRESHOLD)
        self._include_radar = config.get("include_radar", True)

        # Initialize Adaptive Weight Engine
        self._weight_engine = self._init_weight_engine(profile_name)
        self._logger.info(f"AdaptiveWeightEngine initialized with profile: {profile_name}")

        # Initialize Conflict Resolver
        conflict_weights = config.get("conflict_weights")
        self._conflict_resolver = ConflictResolver(weights=conflict_weights)
        self._logger.info(
            f"ConflictResolver initialized with weights: "
            f"accuracy={self._conflict_resolver.weights['accuracy']:.2f}, "
            f"utility={self._conflict_resolver.weights['utility']:.2f}"
        )

        # Initialize SCOUT Pipeline
        self._scout_pipeline = ScoutPipeline(
            include_radar=self._include_radar,
            strict_mode=self._strict_mode
        )
        self._logger.info("ScoutPipeline initialized")

        # Register custom validators
        self._custom_validators: List[Callable[[Dict], List[Conflict]]] = []
        for validator in config.get("custom_validators", []):
            if callable(validator):
                self._custom_validators.append(validator)

        # Decision log for audit trail
        self._decision_log: List[Dict[str, Any]] = []

        self._logger.info(
            f"Guardian initialized: strict_mode={self._strict_mode}, "
            f"score_threshold={self._score_threshold}"
        )

    def _init_weight_engine(self, profile_name: str) -> AdaptiveWeightEngine:
        """Initialize the adaptive weight engine with specified profile."""
        try:
            profile = WeightProfile[profile_name]
        except KeyError:
            valid_profiles = [p.name for p in WeightProfile]
            raise ValueError(
                f"Invalid weight profile '{profile_name}'. "
                f"Valid profiles: {valid_profiles}"
            )
        return AdaptiveWeightEngine(default_profile=profile)

    # =========================================================================
    # Main Validation Methods
    # =========================================================================

    def validate_content(self, content: Dict[str, Any]) -> GuardianResult:
        """
        Validate content through the complete Guardian validation loop.

        This is the main entry point for validation. It orchestrates
        the entire validation process including SCOUT analysis,
        conflict detection, and resolution.

        Args:
            content: Content dictionary containing:
                - subject: Subject being validated (required)
                - domain: Domain category (required)
                - claims: List of claims to validate
                - evidence: List of supporting evidence
                - volatility: Domain volatility level
                - confidence: Initial confidence score
                - metadata: Additional context data

        Returns:
            GuardianResult with complete validation outcome

        Raises:
            ValueError: If required content fields are missing
        """
        start_time = datetime.utcnow()
        content_id = content.get("id", content.get("subject", "unknown"))

        self._logger.info(f"Starting validation for content: {content_id}")

        # Validate required fields
        if "subject" not in content or "domain" not in content:
            raise ValueError("Content must contain 'subject' and 'domain' fields")

        # Determine validation mode
        mode = ValidationMode(content.get("mode", "standard"))

        try:
            # Step 1: Run SCOUT Pipeline
            scout_output = self._run_scout_pipeline(content)

            # Step 2: Calculate weighted scores
            scores = self._calculate_scores(content, scout_output)

            # Step 3: Detect conflicts
            conflicts = self.detect_conflicts({
                "content": content,
                "scout_output": scout_output,
                "scores": scores,
            })

            # Step 4: Deterministic Validation Loop (#3)
            # If conflicts detected, invoke weight engine to evaluate alternatives
            resolutions: List[Resolution] = []
            if conflicts:
                self._logger.info(f"Processing {len(conflicts)} detected conflicts")
                resolutions = self._process_conflicts(conflicts, content, scores)

            # Step 5: Determine final validity
            valid = self._determine_validity(conflicts, resolutions, scout_output)

            # Calculate duration
            end_time = datetime.utcnow()
            duration_ms = (end_time - start_time).total_seconds() * 1000

            # Build result
            result = GuardianResult(
                valid=valid,
                content_id=content_id,
                mode=mode,
                scout_output=scout_output,
                conflicts=conflicts,
                resolutions=resolutions,
                scores=scores,
                metadata={
                    "config": self._config,
                    "custom_validators_count": len(self._custom_validators),
                    "decisions_logged": len(self._decision_log),
                },
                duration_ms=duration_ms,
            )

            # Log decision
            self._log_decision("validation_complete", {
                "content_id": content_id,
                "valid": valid,
                "conflicts_count": len(conflicts),
                "resolutions_count": len(resolutions),
            })

            self._logger.info(
                f"Validation complete for {content_id}: "
                f"valid={valid}, conflicts={len(conflicts)}, "
                f"duration={duration_ms:.2f}ms"
            )

            return result

        except Exception as e:
            self._logger.error(f"Validation failed for {content_id}: {e}")
            self._log_decision("validation_error", {
                "content_id": content_id,
                "error": str(e),
            })
            raise

    def _run_scout_pipeline(self, content: Dict[str, Any]) -> ScoutOutput:
        """
        Run the SCOUT pipeline for multi-agent analysis.

        Args:
            content: Content to analyze

        Returns:
            ScoutOutput from pipeline execution
        """
        # Build AnalysisContext from content
        context = AnalysisContext(
            subject=content["subject"],
            domain=content["domain"],
            volatility=content.get("volatility", "medium"),
            confidence=content.get("confidence", 0.5),
            context=PipelineContext(content.get("pipeline_context", "validate")),
            metadata=content.get("metadata", {}),
            claims=content.get("claims", []),
            evidence=content.get("evidence", []),
            prior_art=content.get("prior_art", []),
        )

        self._logger.debug(f"Running SCOUT pipeline for: {context.subject}")
        output = self._scout_pipeline.execute_pipeline(context)

        # Log SCOUT decision
        self._log_decision("scout_pipeline", {
            "subject": context.subject,
            "readiness": output.readiness.value,
            "signal_strength": output.signal_strength.name,
            "blocked": output.blocked,
            "hype_flags_count": len(output.hype_flags),
            "risk_flags_count": len(output.risk_flags),
        })

        return output

    def _calculate_scores(
        self,
        content: Dict[str, Any],
        scout_output: ScoutOutput
    ) -> Dict[str, WeightedScore]:
        """
        Calculate weighted scores using the adaptive weight engine.

        Applies domain-specific weights from the configured profile
        to calculate TF, RS, DS, AC scores.

        Args:
            content: Original content
            scout_output: Output from SCOUT pipeline

        Returns:
            Dictionary of calculated weighted scores
        """
        scores: Dict[str, WeightedScore] = {}

        # Extract score components from content or SCOUT output
        # TF: Technical Fidelity - based on evidence quality
        evidence_count = len(content.get("evidence", []))
        tf_score = min(evidence_count * 2.0, 10.0)  # Scale evidence to score

        # RS: Reliability Score - based on hype score (inverted)
        hype_score = 0.0
        if scout_output.agent_outputs.get("devil"):
            hype_score = scout_output.agent_outputs["devil"].get("output", {}).get(
                "hype_score", 0.0
            )
        rs_score = (1.0 - hype_score) * 10.0  # Invert hype to reliability

        # DS: Domain Specificity - based on domain maturity
        ds_score = 7.0  # Default moderate specificity
        if scout_output.agent_outputs.get("radar"):
            maturity = scout_output.agent_outputs["radar"].get("output", {}).get(
                "maturity_score", 0.7
            )
            ds_score = maturity * 10.0

        # AC: Actionability Coefficient - based on readiness
        ac_score = 8.0
        readiness_values = {
            AdoptionReadiness.PRODUCTION_READY: 9.5,
            AdoptionReadiness.EARLY_ADOPTER: 8.0,
            AdoptionReadiness.EXPERIMENTAL: 5.0,
            AdoptionReadiness.VAPORWARE: 2.0,
        }
        ac_score = readiness_values.get(scout_output.readiness, 7.0)

        # Calculate weighted score using adaptive engine
        weighted_score = self._weight_engine.calculate_score_detailed(
            tf=tf_score,
            rs=rs_score,
            ds=ds_score,
            ac=ac_score,
        )
        scores["primary"] = weighted_score

        # Log score calculation
        self._log_decision("score_calculation", {
            "tf": tf_score,
            "rs": rs_score,
            "ds": ds_score,
            "ac": ac_score,
            "weighted_score": weighted_score.score,
            "profile": weighted_score.profile.name,
        })

        self._logger.debug(
            f"Calculated scores: TF={tf_score:.1f}, RS={rs_score:.1f}, "
            f"DS={ds_score:.1f}, AC={ac_score:.1f}, "
            f"weighted={weighted_score.score:.3f}"
        )

        return scores

    # =========================================================================
    # Conflict Detection and Resolution
    # =========================================================================

    def detect_conflicts(self, context: Dict[str, Any]) -> List[Conflict]:
        """
        Detect conflicts from validation context.

        Analyzes SCOUT output, scores, and content to identify
        conflicts that need resolution.

        Args:
            context: Validation context containing:
                - content: Original content dictionary
                - scout_output: ScoutOutput from pipeline
                - scores: Calculated weighted scores

        Returns:
            List of detected Conflict instances
        """
        conflicts: List[Conflict] = []
        content = context.get("content", {})
        scout_output = context.get("scout_output")
        scores = context.get("scores", {})

        if not scout_output:
            return conflicts

        # Check for hype detection conflicts
        if scout_output.hype_flags:
            conflicts.append(Conflict(
                conflict_type=ConflictType.HYPE_DETECTED,
                severity=3,
                description=f"Detected {len(scout_output.hype_flags)} hype indicators",
                source="DEVIL_agent",
                context={"hype_flags": scout_output.hype_flags},
                resolution_hint="Review and verify marketing claims against evidence",
            ))

        # Check for risk flags
        if scout_output.risk_flags:
            severity = 4 if len(scout_output.risk_flags) > 3 else 3
            conflicts.append(Conflict(
                conflict_type=ConflictType.RISK_FLAG,
                severity=severity,
                description=f"Identified {len(scout_output.risk_flags)} risk factors",
                source="DEVIL_agent",
                context={"risk_flags": scout_output.risk_flags},
                resolution_hint="Address risk factors or adjust adoption strategy",
            ))

        # Check for EVAL veto
        if scout_output.blocked and scout_output.veto_reason:
            conflicts.append(Conflict(
                conflict_type=ConflictType.VETO_TRIGGERED,
                severity=5,
                description=f"Strategy synthesis blocked: {scout_output.veto_reason}",
                source="EVAL_agent",
                context={
                    "readiness": scout_output.readiness.value,
                    "veto_reason": scout_output.veto_reason,
                },
                resolution_hint="Address readiness concerns before proceeding",
            ))

        # Check for readiness blockers
        if scout_output.readiness in (
            AdoptionReadiness.EXPERIMENTAL,
            AdoptionReadiness.VAPORWARE
        ):
            conflicts.append(Conflict(
                conflict_type=ConflictType.READINESS_BLOCKER,
                severity=4 if scout_output.readiness == AdoptionReadiness.VAPORWARE else 3,
                description=f"Readiness tier '{scout_output.readiness.value}' may block production use",
                source="EVAL_agent",
                context={"readiness": scout_output.readiness.value},
                resolution_hint="Consider staging or experimental deployment path",
            ))

        # Check score threshold
        primary_score = scores.get("primary")
        if primary_score and primary_score.score < self._score_threshold:
            conflicts.append(Conflict(
                conflict_type=ConflictType.SCORE_MISMATCH,
                severity=3,
                description=f"Score {primary_score.score:.2f} below threshold {self._score_threshold}",
                source="WeightEngine",
                context={
                    "score": primary_score.score,
                    "threshold": self._score_threshold,
                    "components": primary_score.components,
                },
                resolution_hint="Improve evidence quality or address flagged issues",
            ))

        # Check domain volatility with low confidence
        confidence = content.get("confidence", 0.5)
        volatility = content.get("volatility", "medium")
        if volatility == "high" and confidence < 0.5:
            conflicts.append(Conflict(
                conflict_type=ConflictType.DOMAIN_VOLATILITY,
                severity=3,
                description="High domain volatility with low confidence score",
                source="RADAR_agent",
                context={"volatility": volatility, "confidence": confidence},
                resolution_hint="Gather more evidence or reduce reliance on volatile predictions",
            ))

        # Run custom validators
        for validator in self._custom_validators:
            try:
                custom_conflicts = validator(context)
                conflicts.extend(custom_conflicts)
            except Exception as e:
                self._logger.warning(f"Custom validator failed: {e}")

        # Log conflict detection
        self._log_decision("conflict_detection", {
            "conflicts_found": len(conflicts),
            "conflict_types": [c.conflict_type.value for c in conflicts],
            "critical_count": sum(1 for c in conflicts if c.is_critical()),
        })

        self._logger.info(
            f"Detected {len(conflicts)} conflicts: "
            f"{[c.conflict_type.value for c in conflicts]}"
        )

        return conflicts

    def resolve_conflicts(self, conflicts: List[Conflict]) -> List[Resolution]:
        """
        Resolve detected conflicts using the conflict resolver.

        Applies the conflict resolution formula to determine
        the best course of action for each conflict.

        Args:
            conflicts: List of conflicts to resolve

        Returns:
            List of Resolution instances
        """
        resolutions: List[Resolution] = []

        for conflict in conflicts:
            resolution = self._resolve_single_conflict(conflict)
            resolutions.append(resolution)

            # Log resolution
            self._log_decision("conflict_resolution", {
                "conflict_type": conflict.conflict_type.value,
                "status": resolution.status.value,
                "confidence": resolution.confidence,
            })

        return resolutions

    def _resolve_single_conflict(self, conflict: Conflict) -> Resolution:
        """
        Resolve a single conflict.

        Args:
            conflict: Conflict to resolve

        Returns:
            Resolution for the conflict
        """
        # Handle critical conflicts
        if conflict.is_critical():
            return self._resolve_critical_conflict(conflict)

        # Resolve based on conflict type
        resolution_map = {
            ConflictType.HYPE_DETECTED: self._resolve_hype_conflict,
            ConflictType.RISK_FLAG: self._resolve_risk_conflict,
            ConflictType.VETO_TRIGGERED: self._resolve_veto_conflict,
            ConflictType.READINESS_BLOCKER: self._resolve_readiness_conflict,
            ConflictType.SCORE_MISMATCH: self._resolve_score_conflict,
            ConflictType.DOMAIN_VOLATILITY: self._resolve_volatility_conflict,
            ConflictType.POLICY_VIOLATION: self._resolve_policy_conflict,
            ConflictType.DEPENDENCY_CONFLICT: self._resolve_dependency_conflict,
        }

        resolver = resolution_map.get(
            conflict.conflict_type,
            self._resolve_generic_conflict
        )
        return resolver(conflict)

    def _process_conflicts(
        self,
        conflicts: List[Conflict],
        content: Dict[str, Any],
        scores: Dict[str, WeightedScore]
    ) -> List[Resolution]:
        """
        Process conflicts through the Deterministic Validation Loop (#3).

        If conflict detected, invoke weight_engine.evaluate_alternatives()
        and apply resolution from resolver.resolve().

        Args:
            conflicts: Detected conflicts
            content: Original content
            scores: Calculated scores

        Returns:
            List of applied resolutions
        """
        resolutions: List[Resolution] = []

        for conflict in conflicts:
            # For certain conflicts, evaluate alternatives using weight engine
            if conflict.conflict_type in (
                ConflictType.SCORE_MISMATCH,
                ConflictType.READINESS_BLOCKER,
                ConflictType.DOMAIN_VOLATILITY,
            ):
                # Create alternative options for conflict resolution
                option_a = ConflictMetrics(
                    accuracy=content.get("confidence", 0.5),
                    utility=scores.get("primary", WeightedScore(0, WeightProfile.MIXED, {})).score / 10.0,
                    efficiency=0.7,  # Default efficiency
                    consensus=0.8 if not conflict.is_critical() else 0.4,
                    optimal_context="Current approach",
                )

                # Alternative: modified approach
                option_b = ConflictMetrics(
                    accuracy=min(content.get("confidence", 0.5) + 0.1, 1.0),
                    utility=0.6,
                    efficiency=0.8,
                    consensus=0.7,
                    optimal_context="Alternative with additional verification",
                )

                # Use conflict resolver to determine best option
                decision = self._conflict_resolver.resolve(
                    option_a, option_b,
                    "Current", "Alternative"
                )

                # Log resolution decision
                self._log_decision("conflict_resolution_formula", {
                    "conflict_id": id(conflict),
                    "score_a": decision.score_a,
                    "score_b": decision.score_b,
                    "gap": decision.gap,
                    "winner": decision.winner,
                    "confidence": decision.confidence.value,
                })

                # Apply resolution
                if decision.winner:
                    resolution = Resolution(
                        conflict=conflict,
                        status=ResolutionStatus.RESOLVED,
                        action_taken=f"Selected '{decision.winner}' approach",
                        rationale=decision.rationale or f"Score gap: {decision.gap:.3f}",
                        confidence=1.0 if decision.confidence == DecisionConfidence.HIGH else 0.8,
                        alternatives=[f"Alternative approach: score={decision.score_b:.3f}"],
                    )
                else:
                    # Conditional resolution
                    resolution = Resolution(
                        conflict=conflict,
                        status=ResolutionStatus.ESCALATED,
                        action_taken="Requires additional evaluation",
                        rationale=decision.rationale or "Scores too close to determine",
                        confidence=0.5,
                        alternatives=["Human review recommended"],
                    )

                resolutions.append(resolution)
            else:
                # Use standard resolution for other conflict types
                resolution = self._resolve_single_conflict(conflict)
                resolutions.append(resolution)

        return resolutions

    # =========================================================================
    # Conflict Type-Specific Resolvers
    # =========================================================================

    def _resolve_critical_conflict(self, conflict: Conflict) -> Resolution:
        """Resolve critical (severity >= 4) conflicts."""
        return Resolution(
            conflict=conflict,
            status=ResolutionStatus.BLOCKED,
            action_taken="Validation blocked due to critical conflict",
            rationale=f"Critical conflict (severity={conflict.severity}) requires manual review",
            confidence=1.0,
            alternatives=["Escalate to human review", "Request additional evidence"],
        )

    def _resolve_hype_conflict(self, conflict: Conflict) -> Resolution:
        """Resolve hype detection conflicts."""
        hype_flags = conflict.context.get("hype_flags", [])
        return Resolution(
            conflict=conflict,
            status=ResolutionStatus.RESOLVED,
            action_taken="Flagged hype indicators for review",
            rationale=f"Identified {len(hype_flags)} hype indicators requiring verification",
            confidence=0.85,
            alternatives=["Remove marketing language", "Add supporting evidence"],
        )

    def _resolve_risk_conflict(self, conflict: Conflict) -> Resolution:
        """Resolve risk flag conflicts."""
        risk_flags = conflict.context.get("risk_flags", [])
        if conflict.severity >= 4:
            status = ResolutionStatus.ESCALATED
            action = "Escalated for risk assessment"
        else:
            status = ResolutionStatus.RESOLVED
            action = "Risk factors noted in validation report"

        return Resolution(
            conflict=conflict,
            status=status,
            action_taken=action,
            rationale=f"Risk flags: {', '.join(risk_flags[:3])}{'...' if len(risk_flags) > 3 else ''}",
            confidence=0.8,
            alternatives=["Mitigate risks", "Accept with documentation"],
        )

    def _resolve_veto_conflict(self, conflict: Conflict) -> Resolution:
        """Resolve EVAL veto conflicts."""
        return Resolution(
            conflict=conflict,
            status=ResolutionStatus.BLOCKED,
            action_taken="Strategy synthesis blocked by EVAL veto",
            rationale=conflict.context.get("veto_reason", "EVAL veto triggered"),
            confidence=1.0,
            alternatives=[
                "Address readiness concerns",
                "Use experimental deployment path",
                "Reassess when conditions improve",
            ],
        )

    def _resolve_readiness_conflict(self, conflict: Conflict) -> Resolution:
        """Resolve readiness tier conflicts."""
        readiness = conflict.context.get("readiness", "unknown")
        return Resolution(
            conflict=conflict,
            status=ResolutionStatus.RESOLVED,
            action_taken=f"Applied readiness constraints for {readiness}",
            rationale=f"Readiness tier '{readiness}' requires specific deployment approach",
            confidence=0.9,
            alternatives=[
                "Use early adopter path",
                "Staged rollout with monitoring",
                "Experimental environment only",
            ],
        )

    def _resolve_score_conflict(self, conflict: Conflict) -> Resolution:
        """Resolve score threshold conflicts."""
        return Resolution(
            conflict=conflict,
            status=ResolutionStatus.RESOLVED,
            action_taken="Score threshold gap documented",
            rationale=f"Score {conflict.context.get('score', 0):.2f} below threshold, flagged for review",
            confidence=0.75,
            alternatives=[
                "Improve evidence quality",
                "Adjust weight profile",
                "Accept with caveats",
            ],
        )

    def _resolve_volatility_conflict(self, conflict: Conflict) -> Resolution:
        """Resolve domain volatility conflicts."""
        return Resolution(
            conflict=conflict,
            status=ResolutionStatus.RESOLVED,
            action_taken="Added volatility caveats to validation",
            rationale="High volatility domain requires caution in predictions",
            confidence=0.8,
            alternatives=[
                "Gather more evidence",
                "Reduce prediction confidence",
                "Use conservative estimates",
            ],
        )

    def _resolve_policy_conflict(self, conflict: Conflict) -> Resolution:
        """Resolve policy violation conflicts."""
        return Resolution(
            conflict=conflict,
            status=ResolutionStatus.ESCALATED,
            action_taken="Policy violation escalated",
            rationale="Content may violate validation policies",
            confidence=0.9,
            alternatives=["Review policy compliance", "Modify content"],
        )

    def _resolve_dependency_conflict(self, conflict: Conflict) -> Resolution:
        """Resolve dependency conflicts."""
        return Resolution(
            conflict=conflict,
            status=ResolutionStatus.DEFERRED,
            action_taken="Dependency resolution deferred",
            rationale="Conflicting dependencies require resolution",
            confidence=0.7,
            alternatives=["Resolve dependencies", "Use alternative approach"],
        )

    def _resolve_generic_conflict(self, conflict: Conflict) -> Resolution:
        """Generic conflict resolver for unknown types."""
        return Resolution(
            conflict=conflict,
            status=ResolutionStatus.ESCALATED,
            action_taken="Escalated for manual review",
            rationale=f"Unknown conflict type: {conflict.conflict_type.value}",
            confidence=0.5,
            alternatives=["Manual review required"],
        )

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def _determine_validity(
        self,
        conflicts: List[Conflict],
        resolutions: List[Resolution],
        scout_output: ScoutOutput
    ) -> bool:
        """
        Determine overall validation validity.

        Args:
            conflicts: Detected conflicts
            resolutions: Applied resolutions
            scout_output: SCOUT pipeline output

        Returns:
            True if validation passes, False otherwise
        """
        # Check for critical unresolved conflicts
        critical_unresolved = [
            c for c in conflicts
            if c.is_critical() and not any(
                r.conflict is c and r.is_successful()
                for r in resolutions
            )
        ]
        if critical_unresolved:
            self._logger.warning(
                f"Validation failed: {len(critical_unresolved)} unresolved critical conflicts"
            )
            return False

        # Check for blocked resolutions
        blocked = [r for r in resolutions if r.status == ResolutionStatus.BLOCKED]
        if blocked:
            self._logger.warning(f"Validation failed: {len(blocked)} blocked resolutions")
            return False

        # In strict mode, any unresolved conflict fails validation
        if self._strict_mode:
            unresolved = [
                c for c in conflicts
                if not any(r.conflict is c for r in resolutions)
            ]
            if unresolved:
                self._logger.warning(
                    f"Validation failed (strict mode): {len(unresolved)} unresolved conflicts"
                )
                return False

        # Check readiness tier
        if scout_output.readiness == AdoptionReadiness.VAPORWARE:
            self._logger.warning("Validation failed: Vaporware readiness tier")
            return False

        # Check if blocked by EVAL
        if scout_output.blocked:
            self._logger.warning("Validation failed: SCOUT pipeline blocked")
            return False

        return True

    def _log_decision(self, decision_type: str, data: Dict[str, Any]) -> None:
        """
        Log a decision for audit trail.

        Args:
            decision_type: Type of decision being logged
            data: Decision data to log
        """
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "decision_type": decision_type,
            "data": data,
        }
        self._decision_log.append(entry)

        # Also log to module logger
        self._logger.debug(f"[DECISION] {decision_type}: {data}")

    def get_decision_log(self) -> List[Dict[str, Any]]:
        """
        Get the complete decision log.

        Returns:
            List of all logged decisions
        """
        return self._decision_log.copy()

    def clear_decision_log(self) -> None:
        """Clear the decision log."""
        self._decision_log.clear()
        self._logger.debug("Decision log cleared")

    @property
    def weight_engine(self) -> AdaptiveWeightEngine:
        """Get the weight engine instance."""
        return self._weight_engine

    @property
    def conflict_resolver(self) -> ConflictResolver:
        """Get the conflict resolver instance."""
        return self._conflict_resolver

    @property
    def scout_pipeline(self) -> ScoutPipeline:
        """Get the SCOUT pipeline instance."""
        return self._scout_pipeline


# =============================================================================
# Factory Function
# =============================================================================

def create_guardian(
    weight_profile: str = "MIXED",
    strict_mode: bool = False,
    score_threshold: float = 7.0,
    **kwargs
) -> Guardian:
    """
    Factory function to create a Guardian instance.

    Args:
        weight_profile: Weight profile name ("TECHNICAL", "MEDICAL_LEGAL", "NARRATIVE", "MIXED")
        strict_mode: Enable strict validation mode
        score_threshold: Minimum score threshold
        **kwargs: Additional configuration options

    Returns:
        Configured Guardian instance

    Example:
        >>> guardian = create_guardian("TECHNICAL", strict_mode=True)
        >>> result = guardian.validate_content({"subject": "Test", "domain": "ai"})
    """
    config = {
        "weight_profile": weight_profile,
        "strict_mode": strict_mode,
        "score_threshold": score_threshold,
        **kwargs
    }
    return Guardian(config)
