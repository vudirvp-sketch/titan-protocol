"""
Gate Manager for TITAN FUSE Protocol.

ITEM-GATE-04: Split Pre/Post Exec Gates
ITEM-GATE-002: GATE_PREPOST_SPLIT_VALIDATION

Separates gate evaluation into two distinct phases:
1. Pre-execution gates: Run before LLM operations
2. Post-execution gates: Run after LLM operations

This separation allows for early detection of policy violations
before expensive LLM calls, and validates outputs after processing.

GATE_04 Pre/Post Split Validation:
- Pre: [validation_pass, idempotent_check]
- Post: [orphan_scan, artifact_verify]

Author: TITAN FUSE Team
Version: 5.0.0
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Callable
from enum import Enum
from datetime import datetime
import logging
import copy
import hashlib

from src.utils.timezone import now_utc, now_utc_iso
# [ITEM-GATE-001] Import GateBehaviorModifier for mode-aware behavior
from src.policy.gate_behavior import (
    GateBehaviorModifier,
    ExecutionMode,
    ModeProfile,
    MODE_PROFILES,
)
# [ITEM-MODEL-002] Import token attribution for per-gate tracking
from src.observability.token_attribution import (
    start_gate as attribution_start_gate,
    end_gate as attribution_end_gate,
)


class GateType(Enum):
    """Type of gate."""
    PRE_EXEC = "pre_exec"
    POST_EXEC = "post_exec"


class GateResult(Enum):
    """Result of gate evaluation."""
    PASS = "PASS"
    FAIL = "FAIL"
    ADVISORY_PASS = "ADVISORY_PASS"
    PENDING = "PENDING"
    SKIPPED = "SKIPPED"


@dataclass
class GateCheck:
    """
    A single gate check.
    
    Attributes:
        name: Gate name
        check_type: Pre or post execution
        description: Human-readable description
        check_fn: Function that performs the check
        required: Whether this gate must pass
        severity: Severity level if gate fails
    """
    name: str
    check_type: GateType
    description: str = ""
    check_fn: Optional[Callable[[Dict], bool]] = None
    required: bool = True
    severity: str = "SEV-2"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "check_type": self.check_type.value,
            "description": self.description,
            "required": self.required,
            "severity": self.severity
        }


@dataclass
class GateCheckResult:
    """Result of a single gate check."""
    gate_name: str
    check_type: GateType
    result: GateResult
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=now_utc_iso)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate_name": self.gate_name,
            "check_type": self.check_type.value,
            "result": self.result.value,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp
        }


@dataclass
class GateManagerResult:
    """Result of gate manager evaluation."""
    overall_result: GateResult
    pre_exec_results: List[GateCheckResult] = field(default_factory=list)
    post_exec_results: List[GateCheckResult] = field(default_factory=list)
    failed_gates: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    execution_time_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_result": self.overall_result.value,
            "pre_exec_results": [r.to_dict() for r in self.pre_exec_results],
            "post_exec_results": [r.to_dict() for r in self.post_exec_results],
            "failed_gates": self.failed_gates,
            "warnings": self.warnings,
            "execution_time_ms": self.execution_time_ms
        }


@dataclass
class PreValidationResult:
    """
    [ITEM-GATE-002] Result of pre-execution validation phase.
    
    Captures the state before patches are applied for GATE_04.
    
    Attributes:
        validation_pass: Whether all validators passed
        idempotent_check: Whether state allows idempotent operations
        state_checksum: Checksum of state for post-validation comparison
        errors: List of error messages if validation failed
    """
    validation_pass: bool
    idempotent_check: bool
    state_checksum: str
    errors: List[str] = field(default_factory=list)
    
    @property
    def passed(self) -> bool:
        """Check if all pre-validation checks passed."""
        return self.validation_pass and self.idempotent_check
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "validation_pass": self.validation_pass,
            "idempotent_check": self.idempotent_check,
            "state_checksum": self.state_checksum,
            "passed": self.passed,
            "errors": self.errors
        }


@dataclass
class PostValidationResult:
    """
    [ITEM-GATE-002] Result of post-execution validation phase.
    
    Validates the state after patches are applied for GATE_04.
    
    Attributes:
        orphan_scan: Whether orphan reference scan passed
        artifact_verify: Whether all required artifacts are verified
        gaps_found: List of gaps discovered during validation
        errors: List of error messages if validation failed
    """
    orphan_scan: bool
    artifact_verify: bool
    gaps_found: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    @property
    def passed(self) -> bool:
        """Check if all post-validation checks passed."""
        return self.orphan_scan and self.artifact_verify
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "orphan_scan": self.orphan_scan,
            "artifact_verify": self.artifact_verify,
            "gaps_found": self.gaps_found,
            "passed": self.passed,
            "errors": self.errors
        }


# Default gate definitions
DEFAULT_PRE_EXEC_GATES = [
    GateCheck(
        name="Policy Check",
        check_type=GateType.PRE_EXEC,
        description="All policies loaded and valid",
        required=True,
        severity="SEV-1"
    ),
    GateCheck(
        name="Access Control",
        check_type=GateType.PRE_EXEC,
        description="User has permissions for operation",
        required=True,
        severity="SEV-1"
    ),
    GateCheck(
        name="Resource Availability",
        check_type=GateType.PRE_EXEC,
        description="Sufficient resources for operation",
        required=True,
        severity="SEV-2"
    ),
    GateCheck(
        name="Input Validation",
        check_type=GateType.PRE_EXEC,
        description="Input data conforms to expected format",
        required=True,
        severity="SEV-2"
    ),
    GateCheck(
        name="Budget Check",
        check_type=GateType.PRE_EXEC,
        description="Token budget available for operation",
        required=False,
        severity="SEV-3"
    ),
    # ITEM-PROT-001: Hyperparameter Enforcement Gate
    GateCheck(
        name="Hyperparameter Check",
        check_type=GateType.PRE_EXEC,
        description="LLM hyperparameters valid for deterministic mode",
        required=True,
        severity="SEV-1"
    )
]

DEFAULT_POST_EXEC_GATES = [
    GateCheck(
        name="Output Structure",
        check_type=GateType.POST_EXEC,
        description="Output conforms to schema",
        required=True,
        severity="SEV-2"
    ),
    GateCheck(
        name="Invariant Validation",
        check_type=GateType.POST_EXEC,
        description="All invariants maintained",
        required=True,
        severity="SEV-1"
    ),
    GateCheck(
        name="Change Verification",
        check_type=GateType.POST_EXEC,
        description="Changes match expected patterns",
        required=True,
        severity="SEV-2"
    ),
    GateCheck(
        name="No Fabrication",
        check_type=GateType.POST_EXEC,
        description="No fabricated content in output",
        required=True,
        severity="SEV-1"
    ),
    GateCheck(
        name="Gap Tracking",
        check_type=GateType.POST_EXEC,
        description="All gaps properly tracked",
        required=False,
        severity="SEV-3"
    )
]


class GateManager:
    """
    ITEM-GATE-04: Manages pre and post-execution gate evaluation.
    ITEM-GATE-001: Mode-aware gate behavior with sensitivity multiplier.
    
    The GateManager provides a structured way to run validation gates
    before and after LLM operations:
    
    **Pre-execution gates** run after intent routing but before the LLM call:
    - Policy Check: Verify all policies are loaded
    - Access Control: Verify user permissions
    - Resource Availability: Check system resources
    - Input Validation: Validate input format
    - Budget Check: Verify token budget
    
    **Post-execution gates** run after LLM output but before returning:
    - Output Structure: Validate output schema
    - Invariant Validation: Check invariants maintained
    - Change Verification: Verify expected changes
    - No Fabrication: Detect fabricated content
    - Gap Tracking: Ensure gaps are tracked
    
    [ITEM-GATE-001] Mode Integration:
    - GateBehaviorModifier is used for mode-aware behavior
    - Sensitivity multiplier adjusts thresholds per mode
    - fail_fast and retry settings are mode-dependent
    
    Usage:
        manager = GateManager()
        
        # Run pre-exec gates with mode awareness
        pre_result = manager.run_pre_exec_gates(context)
        if pre_result.overall_result != GateResult.PASS:
            return pre_result
        
        # Execute LLM operation
        output = llm_operation(context)
        
        # Run post-exec gates
        post_result = manager.run_post_exec_gates(context, output)
        return post_result
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize gate manager.
        
        [ITEM-GATE-001] Enhanced with mode-aware behavior.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        self._logger = logging.getLogger(__name__)
        
        # Initialize gates
        self._pre_exec_gates: Dict[str, GateCheck] = {}
        self._post_exec_gates: Dict[str, GateCheck] = {}
        self._check_functions: Dict[str, Callable] = {}
        
        # [ITEM-GATE-001] Initialize mode-aware behavior
        self._mode_modifier: Optional[GateBehaviorModifier] = None
        self._thresholds: Dict[str, float] = {
            "max_sev1_gaps": 0,
            "max_sev2_gaps": 2,
            "max_sev3_gaps": 5,
            "max_sev4_gaps": 10,
        }
        
        # Load default gates
        self._load_default_gates()
        
        # Load custom gates from config
        self._load_custom_gates()
    
    def _load_default_gates(self) -> None:
        """Load default gate definitions."""
        for gate in DEFAULT_PRE_EXEC_GATES:
            self._pre_exec_gates[gate.name] = gate
        
        for gate in DEFAULT_POST_EXEC_GATES:
            self._post_exec_gates[gate.name] = gate
    
    def _load_custom_gates(self) -> None:
        """Load custom gates from configuration."""
        custom_gates = self.config.get("custom_gates", {})
        
        for gate_name, gate_config in custom_gates.items():
            gate_type = GateType(gate_config.get("type", "pre_exec"))
            gate = GateCheck(
                name=gate_name,
                check_type=gate_type,
                description=gate_config.get("description", ""),
                required=gate_config.get("required", True),
                severity=gate_config.get("severity", "SEV-2")
            )
            
            if gate_type == GateType.PRE_EXEC:
                self._pre_exec_gates[gate_name] = gate
            else:
                self._post_exec_gates[gate_name] = gate
    
    def register_check_function(self, gate_name: str, 
                                 check_fn: Callable[[Dict], bool]) -> None:
        """
        Register a check function for a gate.
        
        Args:
            gate_name: Name of the gate
            check_fn: Function that takes context and returns bool
        """
        self._check_functions[gate_name] = check_fn
    
    def add_gate(self, gate: GateCheck) -> None:
        """
        Add a new gate.
        
        Args:
            gate: GateCheck to add
        """
        if gate.check_type == GateType.PRE_EXEC:
            self._pre_exec_gates[gate.name] = gate
        else:
            self._post_exec_gates[gate.name] = gate
    
    def remove_gate(self, gate_name: str) -> bool:
        """
        Remove a gate.
        
        Args:
            gate_name: Name of gate to remove
            
        Returns:
            True if gate was removed
        """
        if gate_name in self._pre_exec_gates:
            del self._pre_exec_gates[gate_name]
            return True
        if gate_name in self._post_exec_gates:
            del self._post_exec_gates[gate_name]
            return True
        return False
    
    def run_pre_exec_gates(self, context: Dict[str, Any]) -> GateManagerResult:
        """
        Run all pre-execution gates.
        
        ITEM-GATE-04: Pre-exec gates run after intent routing, before LLM call.
        This allows early detection of policy violations.
        
        ITEM-GATE-001: Mode-aware gate behavior with sensitivity multiplier.
        
        Args:
            context: Execution context with input data, policies, etc.
            
        Returns:
            GateManagerResult with evaluation outcome
        """
        start_time = now_utc()
        results: List[GateCheckResult] = []
        failed_gates: List[str] = []
        warnings: List[str] = []
        
        # [ITEM-GATE-001] Get execution mode from context and initialize modifier
        mode_str = context.get("execution_mode", "direct")
        try:
            mode = ExecutionMode(mode_str)
        except ValueError:
            self._logger.warning(
                f"[ITEM-GATE-001] Unknown execution mode '{mode_str}', using DIRECT"
            )
            mode = ExecutionMode.DIRECT
        
        self._mode_modifier = GateBehaviorModifier(mode, self.config)
        
        # [ITEM-GATE-001] Apply sensitivity to thresholds
        adjusted_thresholds = self._mode_modifier.apply_sensitivity(self._thresholds)
        self._logger.info(
            f"[ITEM-GATE-001] Running gates with mode '{mode.value}', "
            f"sensitivity_multiplier={self._mode_modifier.get_mode_profile().sensitivity_multiplier}"
        )
        
        self._logger.info(
            f"Running {len(self._pre_exec_gates)} pre-exec gates"
        )
        
        for gate_name, gate in self._pre_exec_gates.items():
            # [ITEM-MODEL-002] Start token attribution tracking for this gate
            gate_id = f"PRE_{gate_name.replace(' ', '_')}"
            attribution_start_gate(gate_id)
            
            result = self._run_single_gate(gate, context)
            results.append(result)
            
            # [ITEM-MODEL-002] End token attribution tracking
            # Pre-exec gates typically don't use LLM tokens
            attribution_end_gate(gate_id, tokens_used=0)
            
            self._logger.debug(
                f"[ITEM-MODEL-002] Completed pre-exec gate '{gate_name}' "
                f"with token attribution tracking"
            )
            
            if result.result == GateResult.FAIL:
                failed_gates.append(gate_name)
                
                # [ITEM-GATE-001] Check if should fail fast
                error_severity = gate.severity  # Use gate's configured severity
                if self._mode_modifier.should_fail_fast(error_severity):
                    self._logger.error(
                        f"[ITEM-GATE-001] Mode '{mode.value}' failing fast on "
                        f"gate '{gate_name}' with severity {error_severity}"
                    )
                    # Return immediately on fail-fast
                    end_time = now_utc()
                    return GateManagerResult(
                        overall_result=GateResult.FAIL,
                        pre_exec_results=results,
                        failed_gates=failed_gates,
                        warnings=[
                            f"[ITEM-GATE-001] Fail-fast triggered by gate '{gate_name}'"
                        ],
                        execution_time_ms=(end_time - start_time).total_seconds() * 1000
                    )
                
                if gate.required:
                    self._logger.error(
                        f"[gate_manager] Pre-exec gate '{gate_name}' FAILED: "
                        f"{result.message}"
                    )
                else:
                    warnings.append(f"Optional gate '{gate_name}' failed: {result.message}")
                    self._logger.warning(
                        f"[gate_manager] Optional pre-exec gate '{gate_name}' failed: "
                        f"{result.message}"
                    )
        
        # Determine overall result
        required_failures = [
            g for g in failed_gates 
            if self._pre_exec_gates[g].required
        ]
        
        if required_failures:
            overall_result = GateResult.FAIL
        elif failed_gates:
            overall_result = GateResult.ADVISORY_PASS
        else:
            overall_result = GateResult.PASS
        
        end_time = now_utc()
        execution_time_ms = (end_time - start_time).total_seconds() * 1000
        
        return GateManagerResult(
            overall_result=overall_result,
            pre_exec_results=results,
            failed_gates=failed_gates,
            warnings=warnings,
            execution_time_ms=execution_time_ms
        )
    
    def run_post_exec_gates(self, context: Dict[str, Any],
                            output: Dict[str, Any]) -> GateManagerResult:
        """
        Run all post-execution gates.
        
        ITEM-GATE-04: Post-exec gates run after LLM output, before returning.
        This validates that outputs meet quality standards.
        
        Args:
            context: Execution context
            output: Output from LLM operation
            
        Returns:
            GateManagerResult with evaluation outcome
        """
        start_time = now_utc()
        results: List[GateCheckResult] = []
        failed_gates: List[str] = []
        warnings: List[str] = []
        
        # Combine context and output for post-exec checks
        check_context = {**context, "output": output}
        
        self._logger.info(
            f"Running {len(self._post_exec_gates)} post-exec gates"
        )
        
        for gate_name, gate in self._post_exec_gates.items():
            # [ITEM-MODEL-002] Start token attribution tracking for this gate
            gate_id = f"POST_{gate_name.replace(' ', '_')}"
            attribution_start_gate(gate_id)
            
            result = self._run_single_gate(gate, check_context)
            results.append(result)
            
            # [ITEM-MODEL-002] End token attribution tracking
            # Post-exec gates typically don't use LLM tokens
            attribution_end_gate(gate_id, tokens_used=0)
            
            self._logger.debug(
                f"[ITEM-MODEL-002] Completed post-exec gate '{gate_name}' "
                f"with token attribution tracking"
            )
            
            if result.result == GateResult.FAIL:
                failed_gates.append(gate_name)
                if gate.required:
                    self._logger.error(
                        f"[gate_manager] Post-exec gate '{gate_name}' FAILED: "
                        f"{result.message}"
                    )
                else:
                    warnings.append(f"Optional gate '{gate_name}' failed: {result.message}")
        
        # Determine overall result
        required_failures = [
            g for g in failed_gates 
            if self._post_exec_gates[g].required
        ]
        
        if required_failures:
            overall_result = GateResult.FAIL
        elif failed_gates:
            overall_result = GateResult.ADVISORY_PASS
        else:
            overall_result = GateResult.PASS
        
        end_time = now_utc()
        execution_time_ms = (end_time - start_time).total_seconds() * 1000
        
        return GateManagerResult(
            overall_result=overall_result,
            post_exec_results=results,
            failed_gates=failed_gates,
            warnings=warnings,
            execution_time_ms=execution_time_ms
        )
    
    def _run_single_gate(self, gate: GateCheck, 
                         context: Dict[str, Any]) -> GateCheckResult:
        """
        Run a single gate check.
        
        Args:
            gate: Gate to run
            context: Execution context
            
        Returns:
            GateCheckResult with outcome
        """
        # Check if a custom function is registered
        if gate.name in self._check_functions:
            try:
                passed = self._check_functions[gate.name](context)
                if passed:
                    return GateCheckResult(
                        gate_name=gate.name,
                        check_type=gate.check_type,
                        result=GateResult.PASS,
                        message=f"Gate '{gate.name}' passed"
                    )
                else:
                    return GateCheckResult(
                        gate_name=gate.name,
                        check_type=gate.check_type,
                        result=GateResult.FAIL,
                        message=f"Gate '{gate.name}' check returned false"
                    )
            except Exception as e:
                return GateCheckResult(
                    gate_name=gate.name,
                    check_type=gate.check_type,
                    result=GateResult.FAIL,
                    message=f"Gate '{gate.name}' raised exception: {e}",
                    details={"exception": str(e)}
                )
        
        # Default implementations for standard gates
        return self._run_default_gate_check(gate, context)
    
    def _run_default_gate_check(self, gate: GateCheck,
                                 context: Dict[str, Any]) -> GateCheckResult:
        """
        Run default implementation for standard gates.
        
        Args:
            gate: Gate to run
            context: Execution context
            
        Returns:
            GateCheckResult with outcome
        """
        # Default implementations for known gates
        if gate.name == "Policy Check":
            return self._check_policies(context)
        elif gate.name == "Access Control":
            return self._check_access_control(context)
        elif gate.name == "Resource Availability":
            return self._check_resources(context)
        elif gate.name == "Input Validation":
            return self._check_input_validation(context)
        elif gate.name == "Budget Check":
            return self._check_budget(context)
        elif gate.name == "Output Structure":
            return self._check_output_structure(context)
        elif gate.name == "Invariant Validation":
            return self._check_invariants(context)
        elif gate.name == "Change Verification":
            return self._check_changes(context)
        elif gate.name == "No Fabrication":
            return self._check_no_fabrication(context)
        elif gate.name == "Gap Tracking":
            return self._check_gap_tracking(context)
        elif gate.name == "Hyperparameter Check":
            return self._check_hyperparameters(context)
        else:
            # Unknown gate - skip with warning
            return GateCheckResult(
                gate_name=gate.name,
                check_type=gate.check_type,
                result=GateResult.SKIPPED,
                message=f"No check function registered for gate '{gate.name}'"
            )
    
    # Default gate implementations
    
    def _check_policies(self, context: Dict[str, Any]) -> GateCheckResult:
        """Check that policies are loaded and valid."""
        policies = context.get("policies", {})
        
        if not policies:
            return GateCheckResult(
                gate_name="Policy Check",
                check_type=GateType.PRE_EXEC,
                result=GateResult.FAIL,
                message="No policies loaded"
            )
        
        return GateCheckResult(
            gate_name="Policy Check",
            check_type=GateType.PRE_EXEC,
            result=GateResult.PASS,
            message=f"{len(policies)} policies loaded"
        )
    
    def _check_access_control(self, context: Dict[str, Any]) -> GateCheckResult:
        """Check user permissions."""
        user = context.get("user", {})
        permissions = context.get("required_permissions", [])
        
        if permissions and not user:
            return GateCheckResult(
                gate_name="Access Control",
                check_type=GateType.PRE_EXEC,
                result=GateResult.FAIL,
                message="User context required for permission check"
            )
        
        user_perms = user.get("permissions", [])
        missing = [p for p in permissions if p not in user_perms]
        
        if missing:
            return GateCheckResult(
                gate_name="Access Control",
                check_type=GateType.PRE_EXEC,
                result=GateResult.FAIL,
                message=f"Missing permissions: {missing}"
            )
        
        return GateCheckResult(
            gate_name="Access Control",
            check_type=GateType.PRE_EXEC,
            result=GateResult.PASS,
            message="All permissions verified"
        )
    
    def _check_resources(self, context: Dict[str, Any]) -> GateCheckResult:
        """Check resource availability."""
        resources = context.get("resources", {})
        
        required = resources.get("required", {})
        available = resources.get("available", {})
        
        issues = []
        for resource, amount in required.items():
            if available.get(resource, 0) < amount:
                issues.append(f"{resource}: need {amount}, have {available.get(resource, 0)}")
        
        if issues:
            return GateCheckResult(
                gate_name="Resource Availability",
                check_type=GateType.PRE_EXEC,
                result=GateResult.FAIL,
                message=f"Insufficient resources: {', '.join(issues)}"
            )
        
        return GateCheckResult(
            gate_name="Resource Availability",
            check_type=GateType.PRE_EXEC,
            result=GateResult.PASS,
            message="All resources available"
        )
    
    def _check_input_validation(self, context: Dict[str, Any]) -> GateCheckResult:
        """Validate input format."""
        input_data = context.get("input", {})
        schema = context.get("input_schema", {})
        
        if not schema:
            # No schema defined, pass by default
            return GateCheckResult(
                gate_name="Input Validation",
                check_type=GateType.PRE_EXEC,
                result=GateResult.PASS,
                message="No input schema defined"
            )
        
        # Basic validation
        required_fields = schema.get("required", [])
        missing = [f for f in required_fields if f not in input_data]
        
        if missing:
            return GateCheckResult(
                gate_name="Input Validation",
                check_type=GateType.PRE_EXEC,
                result=GateResult.FAIL,
                message=f"Missing required fields: {missing}"
            )
        
        return GateCheckResult(
            gate_name="Input Validation",
            check_type=GateType.PRE_EXEC,
            result=GateResult.PASS,
            message="Input validation passed"
        )
    
    def _check_budget(self, context: Dict[str, Any]) -> GateCheckResult:
        """Check token budget availability."""
        budget = context.get("budget", {})
        
        available = budget.get("available", 0)
        required = budget.get("required", 0)
        
        if available < required:
            return GateCheckResult(
                gate_name="Budget Check",
                check_type=GateType.PRE_EXEC,
                result=GateResult.FAIL,
                message=f"Insufficient budget: {available} < {required}",
                details={"available": available, "required": required}
            )
        
        return GateCheckResult(
            gate_name="Budget Check",
            check_type=GateType.PRE_EXEC,
            result=GateResult.PASS,
            message=f"Budget available: {available} tokens"
        )
    
    def _check_output_structure(self, context: Dict[str, Any]) -> GateCheckResult:
        """Validate output structure."""
        output = context.get("output", {})
        schema = context.get("output_schema", {})
        
        if not schema:
            return GateCheckResult(
                gate_name="Output Structure",
                check_type=GateType.POST_EXEC,
                result=GateResult.PASS,
                message="No output schema defined"
            )
        
        required_fields = schema.get("required", [])
        missing = [f for f in required_fields if f not in output]
        
        if missing:
            return GateCheckResult(
                gate_name="Output Structure",
                check_type=GateType.POST_EXEC,
                result=GateResult.FAIL,
                message=f"Output missing required fields: {missing}"
            )
        
        return GateCheckResult(
            gate_name="Output Structure",
            check_type=GateType.POST_EXEC,
            result=GateResult.PASS,
            message="Output structure valid"
        )
    
    def _check_invariants(self, context: Dict[str, Any]) -> GateCheckResult:
        """Check that invariants are maintained."""
        invariants = context.get("invariants", {})
        output = context.get("output", {})
        
        violations = []
        for name, check in invariants.items():
            if callable(check):
                try:
                    if not check(output):
                        violations.append(name)
                except Exception as e:
                    violations.append(f"{name}: {e}")
            elif isinstance(check, dict):
                # Dict-based invariant check
                expected = check.get("expected")
                actual = output.get(check.get("field"))
                if expected is not None and actual != expected:
                    violations.append(f"{name}: expected {expected}, got {actual}")
        
        if violations:
            return GateCheckResult(
                gate_name="Invariant Validation",
                check_type=GateType.POST_EXEC,
                result=GateResult.FAIL,
                message=f"Invariant violations: {violations}"
            )
        
        return GateCheckResult(
            gate_name="Invariant Validation",
            check_type=GateType.POST_EXEC,
            result=GateResult.PASS,
            message="All invariants maintained"
        )
    
    def _check_changes(self, context: Dict[str, Any]) -> GateCheckResult:
        """Verify changes match expected patterns."""
        output = context.get("output", {})
        changes = output.get("changes", [])
        expected_patterns = context.get("expected_change_patterns", [])
        
        if not expected_patterns:
            return GateCheckResult(
                gate_name="Change Verification",
                check_type=GateType.POST_EXEC,
                result=GateResult.PASS,
                message="No change patterns specified"
            )
        
        # Check that changes match at least one pattern
        unexpected = []
        for change in changes:
            change_type = change.get("type", "")
            if not any(p in change_type for p in expected_patterns):
                unexpected.append(change_type)
        
        if unexpected:
            return GateCheckResult(
                gate_name="Change Verification",
                check_type=GateType.POST_EXEC,
                result=GateResult.FAIL,
                message=f"Unexpected change types: {unexpected[:5]}"  # Limit output
            )
        
        return GateCheckResult(
            gate_name="Change Verification",
            check_type=GateType.POST_EXEC,
            result=GateResult.PASS,
            message="All changes match expected patterns"
        )
    
    def _check_no_fabrication(self, context: Dict[str, Any]) -> GateCheckResult:
        """Check for fabricated content in output."""
        output = context.get("output", {})
        
        # Check for common fabrication indicators
        fabrication_indicators = [
            "TODO:", "FIXME:", "[PLACEHOLDER]", "[INSERT", 
            "[NOT IMPLEMENTED]", "This is a placeholder"
        ]
        
        output_str = str(output)
        found = [ind for ind in fabrication_indicators if ind in output_str]
        
        if found:
            return GateCheckResult(
                gate_name="No Fabrication",
                check_type=GateType.POST_EXEC,
                result=GateResult.FAIL,
                message=f"Fabrication indicators found: {found}"
            )
        
        return GateCheckResult(
            gate_name="No Fabrication",
            check_type=GateType.POST_EXEC,
            result=GateResult.PASS,
            message="No fabrication detected"
        )
    
    def _check_gap_tracking(self, context: Dict[str, Any]) -> GateCheckResult:
        """Check that gaps are properly tracked."""
        output = context.get("output", {})
        gaps = output.get("gaps", [])
        
        # Verify gap structure
        invalid_gaps = []
        for gap in gaps:
            if not gap.get("id") and not gap.get("gap_id"):
                invalid_gaps.append("missing id")
            if not gap.get("severity"):
                invalid_gaps.append("missing severity")
        
        if invalid_gaps:
            return GateCheckResult(
                gate_name="Gap Tracking",
                check_type=GateType.POST_EXEC,
                result=GateResult.ADVISORY_PASS,  # Not critical
                message=f"Gap tracking issues: {invalid_gaps[:5]}"
            )
        
        return GateCheckResult(
            gate_name="Gap Tracking",
            check_type=GateType.POST_EXEC,
            result=GateResult.PASS,
            message=f"{len(gaps)} gaps properly tracked"
        )
    
    def _check_hyperparameters(self, context: Dict[str, Any]) -> GateCheckResult:
        """
        ITEM-PROT-001: Check LLM hyperparameters for deterministic mode.
        
        Validates that LLM call parameters meet deterministic requirements:
        - temperature must be 0.0 in strict mode
        - top_p must be ≤ 0.1 in strict mode
        - seed must be a valid integer
        
        Args:
            context: Execution context containing 'llm_params' and 'determinism_mode'
        
        Returns:
            GateCheckResult with validation outcome
        """
        # Import here to avoid circular imports
        from src.validation.guardian import (
            HyperparameterValidator,
            HyperparameterConfig,
            EnforcementMode,
            ViolationAction,
        )
        
        # Get LLM parameters from context
        llm_params = context.get("llm_params", {})
        determinism_mode = context.get("determinism_mode", "strict")
        hyperparam_config = context.get("hyperparameters", {})
        
        # Skip check if no LLM parameters provided
        if not llm_params:
            return GateCheckResult(
                gate_name="Hyperparameter Check",
                check_type=GateType.PRE_EXEC,
                result=GateResult.PASS,
                message="No LLM parameters to validate"
            )
        
        # Determine enforcement mode from context
        enforcement = EnforcementMode.STRICT if determinism_mode == "strict" else EnforcementMode.RELAXED
        
        # Get on_violation action from config
        on_violation_str = hyperparam_config.get("on_violation", "reject")
        try:
            on_violation = ViolationAction(on_violation_str)
        except ValueError:
            on_violation = ViolationAction.REJECT
        
        # Create validator config
        config = HyperparameterConfig(
            enforcement=enforcement,
            on_violation=on_violation,
            allowed_temperature=hyperparam_config.get("allowed_temperature", 0.0),
            max_top_p=hyperparam_config.get("max_top_p", 0.1),
            require_seed=hyperparam_config.get("require_seed", True),
        )
        
        # Create validator and validate
        validator = HyperparameterValidator(config)
        result = validator.validate_deterministic(llm_params)
        
        if result.valid:
            message = "Hyperparameters valid for deterministic mode"
            if result.was_auto_fixed:
                message = f"Hyperparameters auto-fixed: {[v.param_name for v in result.violations]}"
            
            gate_result = GateResult.PASS
            
            # Store fixed params in context if auto-fixed
            if result.was_auto_fixed:
                context["llm_params"] = result.fixed_params
                self._logger.info(
                    f"[ITEM-PROT-001] Gate auto-fixed hyperparameters: "
                    f"{result.fixed_params}"
                )
        else:
            message = f"Hyperparameter validation failed: {[v.message for v in result.violations]}"
            gate_result = GateResult.FAIL
            self._logger.error(
                f"[ITEM-PROT-001] Gate rejected hyperparameters: "
                f"{[v.message for v in result.violations]}"
            )
        
        return GateCheckResult(
            gate_name="Hyperparameter Check",
            check_type=GateType.PRE_EXEC,
            result=gate_result,
            message=message,
            details={
                "violations": [v.to_dict() for v in result.violations],
                "was_auto_fixed": result.was_auto_fixed,
                "determinism_mode": determinism_mode,
            }
        )
    
    # =========================================================================
    # [ITEM-GATE-002] GATE_04 Pre/Post Split Validation
    # =========================================================================
    
    def _pre_gate_04_validation(self, context: Dict[str, Any]) -> PreValidationResult:
        """
        [ITEM-GATE-002] Pre-execution validation for GATE_04.
        
        Runs BEFORE patches are applied to ensure:
        - All validators pass
        - State allows idempotent operations
        - State is captured for post-validation comparison
        
        Args:
            context: Execution context containing validation requirements
            
        Returns:
            PreValidationResult with validation status and state checksum
        """
        self._logger.info("[ITEM-GATE-002] Running GATE_04 pre-validation")
        errors: List[str] = []
        
        # 1. Run all validators
        validation_pass = self._run_all_validators(context)
        if not validation_pass:
            errors.append("One or more validators failed")
            self._logger.warning("[ITEM-GATE-002] Validation pass check failed")
        
        # 2. Check idempotent state
        idempotent_check = self._check_idempotent_state(context)
        if not idempotent_check:
            errors.append("Idempotent state check failed")
            self._logger.warning("[ITEM-GATE-002] Idempotent state check failed")
        
        # 3. Capture state checksum for post-validation
        state_checksum = self._capture_state_checksum(context)
        self._logger.info(
            f"[ITEM-GATE-002] Pre-validation complete - "
            f"validation_pass={validation_pass}, idempotent_check={idempotent_check}, "
            f"checksum={state_checksum}"
        )
        
        return PreValidationResult(
            validation_pass=validation_pass,
            idempotent_check=idempotent_check,
            state_checksum=state_checksum,
            errors=errors
        )
    
    def _post_gate_04_validation(self, context: Dict[str, Any]) -> PostValidationResult:
        """
        [ITEM-GATE-002] Post-execution validation for GATE_04.
        
        Runs AFTER patches are applied to ensure:
        - No orphan references remain
        - All required artifacts are verified
        - Gaps are properly collected
        
        Args:
            context: Execution context containing output and gaps
            
        Returns:
            PostValidationResult with validation status and gaps found
        """
        self._logger.info("[ITEM-GATE-002] Running GATE_04 post-validation")
        errors: List[str] = []
        
        # 1. Scan for orphan references
        orphan_scan = self._scan_orphan_references(context)
        if not orphan_scan:
            errors.append("Orphan references detected")
            self._logger.warning("[ITEM-GATE-002] Orphan scan failed")
        
        # 2. Verify artifacts
        artifact_verify = self._verify_artifacts(context)
        if not artifact_verify:
            errors.append("Artifact verification failed")
            self._logger.warning("[ITEM-GATE-002] Artifact verification failed")
        
        # 3. Collect gaps found
        gaps_found = context.get("gaps", [])
        gaps_str = []
        for g in gaps_found:
            if hasattr(g, 'to_string'):
                gaps_str.append(g.to_string())
            elif hasattr(g, 'to_dict'):
                gaps_str.append(str(g.to_dict()))
            else:
                gaps_str.append(str(g))
        
        self._logger.info(
            f"[ITEM-GATE-002] Post-validation complete - "
            f"orphan_scan={orphan_scan}, artifact_verify={artifact_verify}, "
            f"gaps_found={len(gaps_str)}"
        )
        
        return PostValidationResult(
            orphan_scan=orphan_scan,
            artifact_verify=artifact_verify,
            gaps_found=gaps_str,
            errors=errors
        )
    
    def _run_all_validators(self, context: Dict[str, Any]) -> bool:
        """
        [ITEM-GATE-002] Run all registered validators.
        
        Executes all pre-execution gates and returns True if all required
        gates pass.
        
        Args:
            context: Execution context
            
        Returns:
            True if all validators pass, False otherwise
        """
        # Run pre-exec gates and check results
        pre_result = self.run_pre_exec_gates(context)
        
        # Check if any required gates failed
        for gate_name in pre_result.failed_gates:
            gate = self._pre_exec_gates.get(gate_name)
            if gate and gate.required:
                self._logger.error(
                    f"[ITEM-GATE-002] Required validator '{gate_name}' failed"
                )
                return False
        
        return pre_result.overall_result in (GateResult.PASS, GateResult.ADVISORY_PASS)
    
    def _check_idempotent_state(self, context: Dict[str, Any]) -> bool:
        """
        [ITEM-GATE-002] Verify state allows idempotent operations.
        
        Checks if the patch can be re-applied with the same result:
        - No pending state changes
        - No duplicate operations in progress
        - State version matches expected
        
        Args:
            context: Execution context with idempotency info
            
        Returns:
            True if idempotent operation is allowed
        """
        # Check for idempotency key
        idempotency_key = context.get("idempotency_key")
        if not idempotency_key:
            # No idempotency key means we assume idempotent
            return True
        
        # Check for duplicate operation tracking
        seen_keys = context.get("seen_idempotency_keys", set())
        if idempotency_key in seen_keys:
            self._logger.warning(
                f"[ITEM-GATE-002] Duplicate idempotency key detected: {idempotency_key}"
            )
            return False
        
        # Check state version if provided
        expected_version = context.get("expected_state_version")
        current_version = context.get("current_state_version")
        if expected_version is not None and current_version != expected_version:
            self._logger.warning(
                f"[ITEM-GATE-002] State version mismatch: "
                f"expected={expected_version}, current={current_version}"
            )
            return False
        
        # Check for pending operations
        pending_ops = context.get("pending_operations", [])
        if pending_ops:
            self._logger.warning(
                f"[ITEM-GATE-002] Pending operations exist: {len(pending_ops)}"
            )
            # Not blocking, just warning
        
        return True
    
    def _capture_state_checksum(self, context: Dict[str, Any]) -> str:
        """
        [ITEM-GATE-002] Capture checksum of current state for comparison.
        
        Creates a hash of the relevant state fields for post-validation
        comparison to detect unexpected changes.
        
        Args:
            context: Execution context
            
        Returns:
            SHA256 checksum (truncated to 16 chars) of state
        """
        # Extract state-relevant fields for checksum
        state_fields = {
            "input": context.get("input", {}),
            "policies": sorted(context.get("policies", {}).keys()),
            "session_id": context.get("session_id", ""),
            "chunk_ids": sorted(context.get("chunks", {}).keys()) if context.get("chunks") else [],
        }
        
        # Create deterministic string representation
        state_str = str(sorted(state_fields.items()))
        
        # Generate checksum
        checksum = hashlib.sha256(state_str.encode()).hexdigest()[:16]
        
        self._logger.debug(
            f"[ITEM-GATE-002] Captured state checksum: {checksum}"
        )
        
        return checksum
    
    def _scan_orphan_references(self, context: Dict[str, Any]) -> bool:
        """
        [ITEM-GATE-002] Scan for orphan file references after changes.
        
        Checks that all referenced files in the output exist and are
        accessible. Detects broken references from patch operations.
        
        Args:
            context: Execution context with output containing references
            
        Returns:
            True if no orphans found, False otherwise
        """
        output = context.get("output", {})
        file_references = context.get("file_references", [])
        
        # Get referenced files from output
        referenced_files = set()
        
        # Check various output structures for file references
        if isinstance(output, dict):
            # Check for explicit file references
            if "files_modified" in output:
                referenced_files.update(output["files_modified"])
            if "files_created" in output:
                referenced_files.update(output["files_created"])
            if "references" in output:
                referenced_files.update(output["references"])
            
            # Check patches for file references
            for patch in output.get("patches", []):
                if "file_path" in patch:
                    referenced_files.add(patch["file_path"])
        
        # Add any provided file references
        referenced_files.update(file_references)
        
        # If no references, pass
        if not referenced_files:
            return True
        
        # Check if all referenced files exist (simulated check)
        # In production, this would verify actual file existence
        existing_files = set(context.get("existing_files", []))
        
        # If existing_files not provided, assume all exist
        if not existing_files:
            self._logger.debug(
                "[ITEM-GATE-002] No existing_files in context, assuming all refs valid"
            )
            return True
        
        orphans = referenced_files - existing_files
        if orphans:
            self._logger.warning(
                f"[ITEM-GATE-002] Orphan references found: {orphans}"
            )
            return False
        
        return True
    
    def _verify_artifacts(self, context: Dict[str, Any]) -> bool:
        """
        [ITEM-GATE-002] Verify all required artifacts are present.
        
        Checks that all artifacts required by the operation are present
        in the output or context.
        
        Args:
            context: Execution context with artifacts and requirements
            
        Returns:
            True if all required artifacts present, False otherwise
        """
        required_artifacts = context.get("required_artifacts", [])
        
        # If no requirements, pass
        if not required_artifacts:
            return True
        
        artifacts = context.get("artifacts", {})
        output = context.get("output", {})
        
        # Check for artifacts in both artifacts dict and output
        available_artifacts = set(artifacts.keys())
        
        # Also check output for artifacts
        if isinstance(output, dict):
            if "artifacts" in output:
                available_artifacts.update(output["artifacts"].keys())
            if "generated_artifacts" in output:
                available_artifacts.update(output["generated_artifacts"])
        
        # Check each required artifact
        missing = []
        for artifact in required_artifacts:
            if artifact not in available_artifacts:
                missing.append(artifact)
        
        if missing:
            self._logger.warning(
                f"[ITEM-GATE-002] Missing required artifacts: {missing}"
            )
            return False
        
        return True
    
    def run_gate_04_with_prepost(
        self, 
        context: Dict[str, Any], 
        execute_patches: Callable[[Dict[str, Any]], Dict[str, Any]]
    ) -> GateManagerResult:
        """
        [ITEM-GATE-002] Execute GATE_04 with pre/post validation phases.
        
        This method implements the full GATE_04 pre/post split validation:
        1. Pre-validation: Run validators, check idempotency, capture state
        2. Execution: Run the provided patch execution function
        3. Post-validation: Scan for orphans, verify artifacts, collect gaps
        
        Args:
            context: Execution context with all required data
            execute_patches: Callable that executes patches and returns output
            
        Returns:
            GateManagerResult with overall status and any warnings/gaps
        """
        start_time = now_utc()
        self._logger.info("[ITEM-GATE-002] Starting GATE_04 with pre/post validation")
        
        # Store pre-validation checksum in context
        pre_checksum_store = {}
        context["_pre_checksum_store"] = pre_checksum_store
        
        # ========== PRE-VALIDATION PHASE ==========
        pre_result = self._pre_gate_04_validation(context)
        
        if not pre_result.passed:
            end_time = now_utc()
            self._logger.error(
                f"[ITEM-GATE-002] Pre-validation failed: {pre_result.errors}"
            )
            return GateManagerResult(
                overall_result=GateResult.FAIL,
                failed_gates=["GATE_04_PRE"],
                warnings=[f"Pre-validation failed: {pre_result.errors}"],
                execution_time_ms=(end_time - start_time).total_seconds() * 1000
            )
        
        # Store checksum for post-validation
        pre_checksum_store["checksum"] = pre_result.state_checksum
        
        # ========== EXECUTION PHASE ==========
        self._logger.info("[ITEM-GATE-002] Executing patches")
        
        try:
            output = execute_patches(context)
            context["output"] = output
            self._logger.info("[ITEM-GATE-002] Patch execution completed successfully")
        except Exception as e:
            end_time = now_utc()
            self._logger.error(
                f"[ITEM-GATE-002] Patch execution failed: {e}"
            )
            return GateManagerResult(
                overall_result=GateResult.FAIL,
                failed_gates=["GATE_04_EXECUTION"],
                warnings=[f"Execution failed: {e}"],
                execution_time_ms=(end_time - start_time).total_seconds() * 1000
            )
        
        # ========== POST-VALIDATION PHASE ==========
        post_result = self._post_gate_04_validation(context)
        
        end_time = now_utc()
        
        if not post_result.passed:
            self._logger.error(
                f"[ITEM-GATE-002] Post-validation failed: {post_result.errors}"
            )
            return GateManagerResult(
                overall_result=GateResult.FAIL,
                failed_gates=["GATE_04_POST"],
                warnings=[f"Post-validation failed: {post_result.errors}"] + post_result.gaps_found,
                execution_time_ms=(end_time - start_time).total_seconds() * 1000
            )
        
        # ========== SUCCESS ==========
        self._logger.info(
            f"[ITEM-GATE-002] GATE_04 validation completed successfully"
        )
        
        return GateManagerResult(
            overall_result=GateResult.PASS,
            warnings=post_result.gaps_found,
            execution_time_ms=(end_time - start_time).total_seconds() * 1000
        )
    
    def list_gates(self) -> Dict[str, List[Dict[str, Any]]]:
        """List all registered gates."""
        return {
            "pre_exec": [g.to_dict() for g in self._pre_exec_gates.values()],
            "post_exec": [g.to_dict() for g in self._post_exec_gates.values()]
        }
    
    def get_gate(self, gate_name: str) -> Optional[GateCheck]:
        """Get a specific gate by name."""
        if gate_name in self._pre_exec_gates:
            return self._pre_exec_gates[gate_name]
        if gate_name in self._post_exec_gates:
            return self._post_exec_gates[gate_name]
        return None


def create_gate_manager(config: Dict[str, Any] = None) -> GateManager:
    """
    Factory function to create a GateManager.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        GateManager instance
    """
    return GateManager(config)


def run_gates_for_operation(context: Dict[str, Any],
                            operation: Callable,
                            config: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Convenience function to run gates around an operation.
    
    Args:
        context: Execution context
        operation: Function to execute between gates
        config: Configuration dictionary
        
    Returns:
        Dict with gate results and operation output
    """
    manager = GateManager(config)
    
    # Run pre-exec gates
    pre_result = manager.run_pre_exec_gates(context)
    if pre_result.overall_result == GateResult.FAIL:
        return {
            "status": "pre_exec_failed",
            "pre_exec_result": pre_result.to_dict(),
            "output": None
        }
    
    # Execute operation
    try:
        output = operation(context)
    except Exception as e:
        return {
            "status": "operation_failed",
            "pre_exec_result": pre_result.to_dict(),
            "output": None,
            "error": str(e)
        }
    
    # Run post-exec gates
    post_result = manager.run_post_exec_gates(context, output or {})
    
    return {
        "status": "complete",
        "pre_exec_result": pre_result.to_dict(),
        "post_exec_result": post_result.to_dict(),
        "output": output
    }
