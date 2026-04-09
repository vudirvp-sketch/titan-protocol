"""
ITEM_012: PolicyAdapter for TITAN Protocol v1.2.0.

This module implements the PolicyAdapter which integrates with
the PolicyEngine to enforce policies during skill execution.

Features:
- Integrate with PolicyEngine from src/policy/policy_engine.py
- Enforce policies during skill execution
- Handle policy violations with appropriate actions
- Emit SECURITY_ALERT events on violations

Integration Points:
- PolicyEngine: Policy evaluation and enforcement
- EventBus: Event emission for security alerts
- PluginInterface: Standard plugin lifecycle

Author: TITAN Protocol Team
Version: 1.2.0
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Callable, TYPE_CHECKING
import logging
import threading

from ..interfaces.plugin_interface import (
    PluginInterface,
    PluginState,
    RoutingDecision,
    RoutingAction,
    ExecutionResult,
    ErrorResult,
    PluginInfo
)

if TYPE_CHECKING:
    from ..events.event_bus import EventBus
    from ..policy.policy_engine import PolicyEngine, Policy, PolicyAction, PolicyResult


class ViolationSeverity(Enum):
    """Severity levels for policy violations."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ViolationAction(Enum):
    """Actions to take for policy violations."""
    LOG = "log"                 # Log only
    WARN = "warn"               # Log and warn
    BLOCK = "block"             # Block the operation
    ABORT = "abort"             # Abort execution
    ESCALATE = "escalate"       # Escalate to security team


@dataclass
class PolicyViolation:
    """
    Record of a policy violation.
    
    Attributes:
        violation_id: Unique identifier for the violation
        policy_name: Name of the violated policy
        skill_id: Skill that caused the violation
        severity: Severity level
        action_taken: Action that was taken
        timestamp: When the violation occurred
        context: Context at time of violation
        details: Additional details
    """
    violation_id: str
    policy_name: str
    skill_id: str
    severity: ViolationSeverity = ViolationSeverity.MEDIUM
    action_taken: ViolationAction = ViolationAction.LOG
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    context: Dict[str, Any] = field(default_factory=dict)
    details: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "violation_id": self.violation_id,
            "policy_name": self.policy_name,
            "skill_id": self.skill_id,
            "severity": self.severity.value,
            "action_taken": self.action_taken.value,
            "timestamp": self.timestamp,
            "context": self.context,
            "details": self.details
        }


@dataclass
class EnforcementResult:
    """
    Result of policy enforcement check.
    
    Attributes:
        allowed: Whether the operation is allowed
        violations: List of violations found
        warnings: List of warnings (non-blocking issues)
        required_actions: Actions required before proceeding
        fallback_skill: Alternative skill if blocked
        fallback_used: Whether fallback was used
    """
    allowed: bool = True
    violations: List[PolicyViolation] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    required_actions: List[str] = field(default_factory=list)
    fallback_skill: Optional[str] = None
    fallback_used: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "allowed": self.allowed,
            "violations": [v.to_dict() for v in self.violations],
            "warnings": self.warnings,
            "required_actions": self.required_actions,
            "fallback_skill": self.fallback_skill,
            "fallback_used": self.fallback_used
        }


@dataclass
class SkillPolicyContext:
    """
    Context for policy evaluation during skill execution.
    
    Attributes:
        skill_id: The skill being executed
        intent: The intent that triggered this skill
        profile: User profile
        inputs: Skill inputs
        operation: Operation type (read, write, execute, etc.)
        resource: Resource being accessed
        session_id: Session identifier
        request_id: Request identifier
        metadata: Additional metadata
    """
    skill_id: str
    intent: str = ""
    profile: Dict[str, Any] = field(default_factory=dict)
    inputs: Dict[str, Any] = field(default_factory=dict)
    operation: str = "execute"
    resource: str = ""
    session_id: str = ""
    request_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_policy_context(self) -> Dict[str, Any]:
        """Convert to context dict for PolicyEngine."""
        return {
            "skill_id": self.skill_id,
            "intent": self.intent,
            "profile": self.profile,
            "inputs": self.inputs,
            "operation": self.operation,
            "resource": self.resource,
            "session_id": self.session_id,
            "request_id": self.request_id,
            "metadata": self.metadata,
            # Standard policy context fields
            "error": None,
            "timeout": False,
            "validation_failed": False,
            "gate_blocked": False,
            "retry_count": 0
        }


class PolicyAdapter(PluginInterface):
    """
    Adapter for policy enforcement during skill execution.
    
    This adapter integrates with the PolicyEngine to enforce
    policies before, during, and after skill execution.
    
    Features:
    - Pre-execution policy checks
    - Runtime policy enforcement
    - Violation handling with configurable actions
    - Security alert emission
    
    Integration Points:
    - PolicyEngine: Policy evaluation
    - EventBus: SECURITY_ALERT event emission
    - PluginInterface: Standard plugin lifecycle
    
    Example:
        >>> adapter = PolicyAdapter(config, event_bus)
        >>> adapter.on_init()
        >>> result = adapter.check_skill_policy("debug", context)
        >>> if result.allowed:
        ...     execute_skill()
        >>> else:
        ...     handle_violations(result.violations)
    """
    
    # Default policy violation mappings
    VIOLATION_SEVERITY_MAP: Dict[str, ViolationSeverity] = {
        "unauthorized_access": ViolationSeverity.CRITICAL,
        "policy_violation": ViolationSeverity.HIGH,
        "rate_limit_exceeded": ViolationSeverity.MEDIUM,
        "input_sanitization": ViolationSeverity.MEDIUM,
        "suspicious_pattern": ViolationSeverity.MEDIUM,
        "prompt_injection_detected": ViolationSeverity.CRITICAL,
        "session_hijack_attempt": ViolationSeverity.CRITICAL,
    }
    
    VIOLATION_ACTION_MAP: Dict[ViolationSeverity, ViolationAction] = {
        ViolationSeverity.LOW: ViolationAction.LOG,
        ViolationSeverity.MEDIUM: ViolationAction.WARN,
        ViolationSeverity.HIGH: ViolationAction.BLOCK,
        ViolationSeverity.CRITICAL: ViolationAction.ABORT,
    }
    
    def __init__(self, config: Dict[str, Any], event_bus: 'EventBus' = None):
        """
        Initialize the PolicyAdapter.
        
        Args:
            config: Configuration dictionary with optional keys:
                - strict_mode: Block on any violation (default: True)
                - emit_security_alerts: Emit SECURITY_ALERT events (default: True)
                - fallback_on_violation: Use fallback skills (default: True)
                - violation_handlers: Custom violation handlers by type
            event_bus: Optional EventBus for event emission
        """
        self._config = config
        self._event_bus = event_bus
        self._state = PluginState.UNINITIALIZED
        self._logger = logging.getLogger(__name__)
        
        # PolicyEngine reference
        self._policy_engine: Optional['PolicyEngine'] = None
        
        # Configuration
        self._strict_mode = config.get("strict_mode", True)
        self._emit_security_alerts = config.get("emit_security_alerts", True)
        self._fallback_on_violation = config.get("fallback_on_violation", True)
        
        # Violation handlers
        self._violation_handlers: Dict[str, Callable[[PolicyViolation], None]] = {}
        self._violation_handlers.update(config.get("violation_handlers", {}))
        
        # Fallback skill mappings
        self._fallback_skills: Dict[str, str] = config.get("fallback_skills", {})
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Metrics
        self._enforcement_count = 0
        self._violation_count = 0
        self._block_count = 0
        self._abort_count = 0
        self._fallback_count = 0
        self._violation_history: List[PolicyViolation] = []
        self._max_history = 100
    
    def on_init(self) -> None:
        """
        Initialize the adapter.
        
        Sets up policy engine integration and registers handlers.
        """
        try:
            self._state = PluginState.INITIALIZING
            self._logger.info("Initializing PolicyAdapter")
            
            # Try to get policy engine
            self._initialize_policy_engine()
            
            # Register default violation handlers
            self._register_default_handlers()
            
            self._state = PluginState.READY
            self._logger.info("PolicyAdapter initialized successfully")
            
        except Exception as e:
            self._state = PluginState.ERROR
            self._logger.error(f"PolicyAdapter initialization failed: {e}")
            raise
    
    def on_route(self, intent: str, context: Dict[str, Any]) -> RoutingDecision:
        """
        Make routing decision based on policy.
        
        Args:
            intent: The classified intent
            context: Execution context
        
        Returns:
            RoutingDecision based on policy evaluation
        """
        if self._state != PluginState.READY:
            return RoutingDecision.use_fallback("PolicyAdapter not ready")
        
        try:
            # Build policy context
            skill_id = context.get("skill_id", "unknown")
            policy_context = SkillPolicyContext(
                skill_id=skill_id,
                intent=intent,
                profile=context.get("user_profile", {}),
                inputs=context.get("inputs", {}),
                operation=context.get("operation", "execute"),
                session_id=context.get("session_id", ""),
                request_id=context.get("request_id", "")
            )
            
            # Check policies
            result = self.check_skill_policy(skill_id, policy_context.to_policy_context())
            
            if not result.allowed:
                if result.violations:
                    severity = max(v.severity for v in result.violations)
                    if severity == ViolationSeverity.CRITICAL:
                        return RoutingDecision.abort_request(
                            f"Policy violation: {result.violations[0].policy_name}"
                        )
                
                if self._fallback_on_violation and result.fallback_skill:
                    return RoutingDecision.redirect_to(
                        target=result.fallback_skill,
                        confidence=0.5,
                        reason=f"Policy violation, using fallback: {result.fallback_skill}"
                    )
                
                return RoutingDecision.use_fallback("Policy violation")
            
            return RoutingDecision.continue_routing("Policy check passed")
            
        except Exception as e:
            self._logger.error(f"Policy routing decision failed: {e}")
            return RoutingDecision.use_fallback(f"Error: {str(e)}")
    
    def on_execute(self, plan: Dict[str, Any]) -> ExecutionResult:
        """
        Execute policy operations.
        
        Args:
            plan: Execution plan with operation type and parameters
        
        Returns:
            ExecutionResult with operation results
        """
        start_time = datetime.utcnow()
        
        if self._state != PluginState.READY:
            return ExecutionResult.failure_result("PolicyAdapter not ready")
        
        try:
            operation = plan.get("operation", "check")
            
            if operation == "check":
                skill_id = plan.get("skill_id", "")
                context = plan.get("context", {})
                result = self.check_skill_policy(skill_id, context)
                
                return ExecutionResult.success_result(
                    outputs={"enforcement_result": result.to_dict()},
                    execution_time_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000),
                    fallback_used=result.fallback_used
                )
            
            elif operation == "enforce":
                skill_id = plan.get("skill_id", "")
                context = plan.get("context", {})
                self.enforce_during_execution(skill_id, context)
                
                return ExecutionResult.success_result(
                    outputs={"enforced": True},
                    execution_time_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000)
                )
            
            elif operation == "record_violation":
                violation_data = plan.get("violation", {})
                violation = PolicyViolation(
                    violation_id=violation_data.get("violation_id", f"viol-{datetime.utcnow().timestamp()}"),
                    policy_name=violation_data.get("policy_name", "unknown"),
                    skill_id=violation_data.get("skill_id", "unknown"),
                    severity=ViolationSeverity(violation_data.get("severity", "medium")),
                    action_taken=ViolationAction(violation_data.get("action_taken", "log")),
                    details=violation_data.get("details", "")
                )
                self._record_violation(violation)
                
                return ExecutionResult.success_result(
                    outputs={"recorded": True},
                    execution_time_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000)
                )
            
            elif operation == "get_stats":
                stats = self.get_stats()
                
                return ExecutionResult.success_result(
                    outputs={"stats": stats},
                    execution_time_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000)
                )
            
            else:
                return ExecutionResult.failure_result(f"Unknown operation: {operation}")
                
        except Exception as e:
            self._logger.error(f"Execution failed: {e}")
            return ExecutionResult.failure_result(str(e))
    
    def on_error(self, error: Exception, context: Dict[str, Any]) -> ErrorResult:
        """
        Handle errors during policy enforcement.
        
        Args:
            error: The exception that occurred
            context: Context where the error occurred
        
        Returns:
            ErrorResult indicating how to proceed
        """
        self._logger.error(f"PolicyAdapter error: {error}")
        
        # Record as potential violation
        if isinstance(error, (PermissionError, RuntimeError)):
            violation = PolicyViolation(
                violation_id=f"viol-{datetime.utcnow().timestamp()}",
                policy_name="error_violation",
                skill_id=context.get("skill_id", "unknown"),
                severity=ViolationSeverity.HIGH,
                action_taken=ViolationAction.BLOCK,
                details=str(error)
            )
            self._record_violation(violation)
        
        # For policy errors, we should fail-safe (block)
        return ErrorResult.unhandled_result(
            str(error),
            RoutingAction.ABORT
        )
    
    def on_shutdown(self) -> None:
        """
        Shutdown the adapter and clean up resources.
        """
        self._logger.info("Shutting down PolicyAdapter")
        
        with self._lock:
            self._violation_handlers.clear()
            self._fallback_skills.clear()
            self._policy_engine = None
            self._state = PluginState.SHUTDOWN
        
        self._logger.info("PolicyAdapter shutdown complete")
    
    def get_info(self) -> PluginInfo:
        """Get plugin information."""
        return PluginInfo(
            plugin_id="PolicyAdapter",
            plugin_type="policy_adapter",
            version="1.2.0",
            description="Enforces policies during skill execution with violation handling and security alerts",
            capabilities=[
                "policy_checking",
                "violation_handling",
                "security_alerts",
                "fallback_management"
            ],
            dependencies=["PolicyEngine", "EventBus"],
            priority=1  # High priority - policies must be checked first
        )
    
    # =========================================================================
    # Policy Engine Integration
    # =========================================================================
    
    def _initialize_policy_engine(self) -> None:
        """Initialize or get the PolicyEngine."""
        try:
            from ..policy.policy_engine import get_policy_engine
            self._policy_engine = get_policy_engine()
            self._logger.info("PolicyEngine integration established")
        except ImportError:
            self._logger.warning("PolicyEngine not available, using standalone mode")
            self._policy_engine = None
    
    def _register_default_handlers(self) -> None:
        """Register default violation handlers."""
        # Handler for critical violations
        def handle_critical(violation: PolicyViolation) -> None:
            self._logger.critical(f"CRITICAL violation: {violation.policy_name} by {violation.skill_id}")
            self._emit_security_alert(violation, "CRITICAL")
        
        # Handler for high severity violations
        def handle_high(violation: PolicyViolation) -> None:
            self._logger.warning(f"HIGH severity violation: {violation.policy_name} by {violation.skill_id}")
            self._emit_security_alert(violation, "HIGH")
        
        self._violation_handlers["critical"] = handle_critical
        self._violation_handlers["high"] = handle_high
    
    # =========================================================================
    # Policy Checking
    # =========================================================================
    
    def check_skill_policy(
        self,
        skill_id: str,
        context: Dict[str, Any]
    ) -> EnforcementResult:
        """
        Check if a skill execution is allowed by policy.
        
        Args:
            skill_id: The skill to check
            context: Execution context
        
        Returns:
            EnforcementResult with allowance status and violations
        """
        with self._lock:
            self._enforcement_count += 1
            result = EnforcementResult()
            
            # If no policy engine, allow with warning
            if not self._policy_engine:
                result.warnings.append("PolicyEngine not available")
                return result
            
            # Evaluate policies
            try:
                policy_results = self._policy_engine.evaluate(context)
                
                for policy_result in policy_results:
                    if policy_result.triggered:
                        # Create violation record
                        violation = self._create_violation(
                            policy_name=policy_result.policy_name,
                            skill_id=skill_id,
                            context=context,
                            details=policy_result.reason
                        )
                        result.violations.append(violation)
                        
                        # Determine action based on policy action
                        if policy_result.action:
                            action_name = policy_result.action.value if hasattr(policy_result.action, 'value') else str(policy_result.action)
                            
                            if action_name in ("abort", "ABORT"):
                                result.allowed = False
                                violation.action_taken = ViolationAction.ABORT
                                self._abort_count += 1
                            elif action_name in ("skip", "block", "BLOCK"):
                                result.allowed = False
                                violation.action_taken = ViolationAction.BLOCK
                                self._block_count += 1
                            elif action_name in ("escalate", "ESCALATE"):
                                violation.action_taken = ViolationAction.ESCALATE
                            elif action_name in ("notify", "warn", "WARN"):
                                violation.action_taken = ViolationAction.WARN
                            else:
                                violation.action_taken = ViolationAction.LOG
                
                # Record violations
                for violation in result.violations:
                    self._record_violation(violation)
                
                # Set fallback if blocked
                if not result.allowed and self._fallback_on_violation:
                    result.fallback_skill = self._fallback_skills.get(skill_id)
                    result.fallback_used = result.fallback_skill is not None
                    if result.fallback_used:
                        self._fallback_count += 1
                
            except Exception as e:
                self._logger.error(f"Policy evaluation failed: {e}")
                result.warnings.append(f"Policy evaluation error: {e}")
                if self._strict_mode:
                    result.allowed = False
            
            return result
    
    def enforce_during_execution(
        self,
        skill_id: str,
        context: Dict[str, Any]
    ) -> EnforcementResult:
        """
        Enforce policies during skill execution.
        
        This is called at checkpoints during skill execution to
        verify ongoing compliance.
        
        Args:
            skill_id: The skill being executed
            context: Current execution context
        
        Returns:
            EnforcementResult with current status
        """
        return self.check_skill_policy(skill_id, context)
    
    def _create_violation(
        self,
        policy_name: str,
        skill_id: str,
        context: Dict[str, Any],
        details: str = ""
    ) -> PolicyViolation:
        """Create a policy violation record."""
        # Determine severity
        severity = self.VIOLATION_SEVERITY_MAP.get(
            policy_name.lower().replace(" ", "_"),
            ViolationSeverity.MEDIUM
        )
        
        # Determine action
        action = self.VIOLATION_ACTION_MAP.get(severity, ViolationAction.WARN)
        
        # Generate ID
        violation_id = f"viol-{datetime.utcnow().timestamp():.0f}-{skill_id[:8]}"
        
        return PolicyViolation(
            violation_id=violation_id,
            policy_name=policy_name,
            skill_id=skill_id,
            severity=severity,
            action_taken=action,
            context={k: v for k, v in context.items() if not k.startswith("_")},
            details=details
        )
    
    def _record_violation(self, violation: PolicyViolation) -> None:
        """Record a policy violation."""
        self._violation_count += 1
        self._violation_history.append(violation)
        
        # Trim history
        if len(self._violation_history) > self._max_history:
            self._violation_history = self._violation_history[-self._max_history:]
        
        # Call handler if exists
        handler_key = violation.severity.value
        if handler_key in self._violation_handlers:
            try:
                self._violation_handlers[handler_key](violation)
            except Exception as e:
                self._logger.error(f"Violation handler failed: {e}")
    
    # =========================================================================
    # Security Alerts
    # =========================================================================
    
    def _emit_security_alert(
        self,
        violation: PolicyViolation,
        severity: str
    ) -> None:
        """
        Emit a SECURITY_ALERT event.
        
        Args:
            violation: The policy violation
            severity: Severity string
        """
        if not self._emit_security_alerts or not self._event_bus:
            return
        
        try:
            self._event_bus.emit_simple(
                event_type="SECURITY_ALERT",
                data={
                    "alert_type": "policy_violation",
                    "severity": severity,
                    "source": "PolicyAdapter",
                    "details": {
                        "violation_id": violation.violation_id,
                        "policy_name": violation.policy_name,
                        "skill_id": violation.skill_id,
                        "action_taken": violation.action_taken.value,
                        "details": violation.details
                    },
                    "session_id": violation.context.get("session_id", ""),
                    "action_taken": violation.action_taken.value
                },
                source="PolicyAdapter"
            )
            self._logger.info(f"Emitted SECURITY_ALERT for violation {violation.violation_id}")
        except Exception as e:
            self._logger.error(f"Failed to emit SECURITY_ALERT: {e}")
    
    # =========================================================================
    # Fallback Management
    # =========================================================================
    
    def register_fallback_skill(self, skill_id: str, fallback_id: str) -> None:
        """
        Register a fallback skill for a skill.
        
        Args:
            skill_id: The primary skill ID
            fallback_id: The fallback skill ID
        """
        with self._lock:
            self._fallback_skills[skill_id] = fallback_id
            self._logger.info(f"Registered fallback: {skill_id} -> {fallback_id}")
    
    def unregister_fallback_skill(self, skill_id: str) -> bool:
        """
        Unregister a fallback skill.
        
        Args:
            skill_id: The skill ID to remove fallback for
        
        Returns:
            True if fallback was removed
        """
        with self._lock:
            if skill_id in self._fallback_skills:
                del self._fallback_skills[skill_id]
                return True
            return False
    
    def get_fallback_skill(self, skill_id: str) -> Optional[str]:
        """
        Get the fallback skill for a skill.
        
        Args:
            skill_id: The skill ID
        
        Returns:
            Fallback skill ID or None
        """
        return self._fallback_skills.get(skill_id)
    
    # =========================================================================
    # Violation Handler Management
    # =========================================================================
    
    def register_violation_handler(
        self,
        severity: str,
        handler: Callable[[PolicyViolation], None]
    ) -> None:
        """
        Register a custom violation handler.
        
        Args:
            severity: Severity level to handle (low, medium, high, critical)
            handler: Handler function
        """
        with self._lock:
            self._violation_handlers[severity.lower()] = handler
    
    # =========================================================================
    # Statistics
    # =========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Get adapter statistics."""
        with self._lock:
            # Calculate violation distribution
            severity_counts = {s.value: 0 for s in ViolationSeverity}
            for v in self._violation_history:
                severity_counts[v.severity.value] += 1
            
            return {
                "state": self._state.value,
                "policy_engine_connected": self._policy_engine is not None,
                "enforcement_count": self._enforcement_count,
                "violation_count": self._violation_count,
                "block_count": self._block_count,
                "abort_count": self._abort_count,
                "fallback_count": self._fallback_count,
                "fallback_skills_registered": len(self._fallback_skills),
                "violation_handlers": len(self._violation_handlers),
                "violation_history_size": len(self._violation_history),
                "violation_by_severity": severity_counts,
                "strict_mode": self._strict_mode,
                "emit_security_alerts": self._emit_security_alerts
            }
    
    def get_violation_history(
        self,
        limit: int = 20,
        severity: ViolationSeverity = None
    ) -> List[PolicyViolation]:
        """
        Get recent violation history.
        
        Args:
            limit: Maximum number to return
            severity: Filter by severity (optional)
        
        Returns:
            List of violations
        """
        with self._lock:
            history = self._violation_history
            
            if severity:
                history = [v for v in history if v.severity == severity]
            
            return history[-limit:]
    
    def clear_violation_history(self) -> int:
        """
        Clear violation history.
        
        Returns:
            Number of violations cleared
        """
        with self._lock:
            count = len(self._violation_history)
            self._violation_history.clear()
            return count


# Factory function
def create_policy_adapter(
    config: Dict[str, Any] = None,
    event_bus: 'EventBus' = None
) -> PolicyAdapter:
    """
    Factory function to create a PolicyAdapter.
    
    Args:
        config: Configuration dictionary
        event_bus: Optional EventBus for events
    
    Returns:
        PolicyAdapter instance
    """
    return PolicyAdapter(config or {}, event_bus)
