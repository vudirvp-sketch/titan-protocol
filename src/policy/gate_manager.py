"""
Gate Manager for TITAN FUSE Protocol.

ITEM-GATE-04: Split Pre/Post Exec Gates

Separates gate evaluation into two distinct phases:
1. Pre-execution gates: Run before LLM operations
2. Post-execution gates: Run after LLM operations

This separation allows for early detection of policy violations
before expensive LLM calls, and validates outputs after processing.

Author: TITAN FUSE Team
Version: 3.3.0
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Callable
from enum import Enum
from datetime import datetime
import logging
import copy


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
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
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
    
    Usage:
        manager = GateManager()
        
        # Run pre-exec gates
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
        
        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        self._logger = logging.getLogger(__name__)
        
        # Initialize gates
        self._pre_exec_gates: Dict[str, GateCheck] = {}
        self._post_exec_gates: Dict[str, GateCheck] = {}
        self._check_functions: Dict[str, Callable] = {}
        
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
        
        Args:
            context: Execution context with input data, policies, etc.
            
        Returns:
            GateManagerResult with evaluation outcome
        """
        start_time = datetime.utcnow()
        results: List[GateCheckResult] = []
        failed_gates: List[str] = []
        warnings: List[str] = []
        
        self._logger.info(
            f"Running {len(self._pre_exec_gates)} pre-exec gates"
        )
        
        for gate_name, gate in self._pre_exec_gates.items():
            result = self._run_single_gate(gate, context)
            results.append(result)
            
            if result.result == GateResult.FAIL:
                failed_gates.append(gate_name)
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
        
        end_time = datetime.utcnow()
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
        start_time = datetime.utcnow()
        results: List[GateCheckResult] = []
        failed_gates: List[str] = []
        warnings: List[str] = []
        
        # Combine context and output for post-exec checks
        check_context = {**context, "output": output}
        
        self._logger.info(
            f"Running {len(self._post_exec_gates)} post-exec gates"
        )
        
        for gate_name, gate in self._post_exec_gates.items():
            result = self._run_single_gate(gate, check_context)
            results.append(result)
            
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
        
        end_time = datetime.utcnow()
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
