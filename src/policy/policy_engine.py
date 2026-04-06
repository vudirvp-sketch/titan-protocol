"""
TITAN FUSE Protocol - Policy Engine

Configurable policy engine for behavior rules.
Separates policy logic from core protocol.

TASK-003: Policy Engine & Autonomous Recovery Loops
"""

import json
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable, Union
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class PolicyCondition(Enum):
    """Conditions for policy evaluation."""
    ALWAYS = "always"
    ON_ERROR = "on_error"
    ON_TIMEOUT = "on_timeout"
    ON_VALIDATION_FAIL = "on_validation_fail"
    ON_GATE_BLOCK = "on_gate_block"
    ON_BUDGET_EXCEEDED = "on_budget_exceeded"
    ON_RETRY_EXHAUSTED = "on_retry_exhausted"
    ON_ROLLBACK = "on_rollback"
    CUSTOM = "custom"


class PolicyAction(Enum):
    """Actions that policies can trigger."""
    RETRY = "retry"
    ROLLBACK = "rollback"
    SKIP = "skip"
    ABORT = "abort"
    NOTIFY = "notify"
    LOG = "log"
    WAIT = "wait"
    ESCALATE = "escalate"
    CUSTOM = "custom"


@dataclass
class PolicyResult:
    """Result of policy evaluation."""
    triggered: bool
    action: Optional[PolicyAction] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "triggered": self.triggered,
            "action": self.action.value if self.action else None,
            "parameters": self.parameters,
            "reason": self.reason,
            "timestamp": self.timestamp
        }


@dataclass
class Policy:
    """
    A policy rule.

    Attributes:
        name: Policy name
        condition: When to evaluate this policy
        action: What action to take
        priority: Priority (higher = evaluated first)
        enabled: Whether policy is active
        max_retries: Maximum retries before action
        parameters: Action parameters
        condition_fn: Custom condition function
        action_fn: Custom action function
        metadata: Additional metadata
    """
    name: str
    condition: PolicyCondition
    action: PolicyAction
    priority: int = 100
    enabled: bool = True
    max_retries: int = 3
    parameters: Dict[str, Any] = field(default_factory=dict)
    condition_fn: Optional[Callable[[Dict[str, Any]], bool]] = None
    action_fn: Optional[Callable[[Dict[str, Any]], Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def evaluate(self, context: Dict[str, Any]) -> PolicyResult:
        """
        Evaluate the policy against a context.

        Args:
            context: Evaluation context

        Returns:
            Policy result
        """
        if not self.enabled:
            return PolicyResult(triggered=False, reason="Policy disabled")

        # Check condition
        should_trigger = self._check_condition(context)

        if should_trigger:
            return PolicyResult(
                triggered=True,
                action=self.action,
                parameters=self.parameters.copy(),
                reason=f"Policy '{self.name}' triggered on condition '{self.condition.value}'"
            )

        return PolicyResult(triggered=False, reason="Condition not met")

    def _check_condition(self, context: Dict[str, Any]) -> bool:
        """Check if condition is met."""
        # Custom condition function takes precedence
        if self.condition_fn:
            try:
                return self.condition_fn(context)
            except Exception:
                return False

        # Built-in conditions
        if self.condition == PolicyCondition.ALWAYS:
            return True

        if self.condition == PolicyCondition.ON_ERROR:
            return context.get("error") is not None

        if self.condition == PolicyCondition.ON_TIMEOUT:
            return context.get("timeout", False)

        if self.condition == PolicyCondition.ON_VALIDATION_FAIL:
            return context.get("validation_failed", False)

        if self.condition == PolicyCondition.ON_GATE_BLOCK:
            return context.get("gate_blocked", False)

        if self.condition == PolicyCondition.ON_BUDGET_EXCEEDED:
            return context.get("budget_exceeded", False)

        if self.condition == PolicyCondition.ON_RETRY_EXHAUSTED:
            retry_count = context.get("retry_count", 0)
            return retry_count >= self.max_retries

        if self.condition == PolicyCondition.ON_ROLLBACK:
            return context.get("rollback_triggered", False)

        return False

    def execute_action(self, context: Dict[str, Any]) -> Any:
        """Execute the policy action."""
        if self.action_fn:
            return self.action_fn(context, self.parameters)

        # Built-in actions return parameters for execution
        return {
            "action": self.action.value,
            "parameters": self.parameters
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "condition": self.condition.value,
            "action": self.action.value,
            "priority": self.priority,
            "enabled": self.enabled,
            "max_retries": self.max_retries,
            "parameters": self.parameters,
            "metadata": self.metadata
        }


class PolicyEngine:
    """
    Engine for evaluating and executing policies.

    Features:
    - Policy registration and management
    - Priority-based evaluation
    - Context-based matching
    - Policy chaining
    - Export/Import

    Usage:
        engine = PolicyEngine()

        # Register a policy
        engine.register(Policy(
            name="retry_on_timeout",
            condition=PolicyCondition.ON_TIMEOUT,
            action=PolicyAction.RETRY,
            max_retries=3,
            parameters={"delay_ms": 1000}
        ))

        # Evaluate policies
        result = engine.evaluate({"timeout": True})
        if result.triggered:
            print(f"Action: {result.action}")
    """

    def __init__(self):
        self._policies: Dict[str, Policy] = {}
        self._evaluation_count: Dict[str, int] = {}
        self._trigger_count: Dict[str, int] = {}

    def register(self, policy: Policy) -> None:
        """Register a policy."""
        self._policies[policy.name] = policy
        self._evaluation_count[policy.name] = 0
        self._trigger_count[policy.name] = 0

    def unregister(self, name: str) -> bool:
        """Unregister a policy."""
        if name in self._policies:
            del self._policies[name]
            return True
        return False

    def get(self, name: str) -> Optional[Policy]:
        """Get a policy by name."""
        return self._policies.get(name)

    def list(self, enabled_only: bool = True) -> List[Policy]:
        """List all policies."""
        policies = list(self._policies.values())
        if enabled_only:
            policies = [p for p in policies if p.enabled]
        return sorted(policies, key=lambda p: p.priority, reverse=True)

    def evaluate(self, context: Dict[str, Any],
                 stop_on_trigger: bool = True) -> List[PolicyResult]:
        """
        Evaluate all policies against a context.

        Args:
            context: Evaluation context
            stop_on_trigger: Stop after first trigger

        Returns:
            List of triggered policy results
        """
        results = []

        for policy in self.list(enabled_only=True):
            self._evaluation_count[policy.name] += 1

            result = policy.evaluate(context)

            if result.triggered:
                self._trigger_count[policy.name] += 1
                results.append(result)

                if stop_on_trigger:
                    break

        return results

    def evaluate_condition(self, condition: PolicyCondition,
                           context: Dict[str, Any]) -> List[PolicyResult]:
        """
        Evaluate policies for a specific condition.

        Args:
            condition: Condition to match
            context: Evaluation context

        Returns:
            List of triggered policy results
        """
        results = []

        for policy in self.list(enabled_only=True):
            if policy.condition == condition:
                result = policy.evaluate(context)
                if result.triggered:
                    results.append(result)

        return results

    def execute(self, policy_name: str,
                context: Dict[str, Any]) -> Any:
        """Execute a specific policy's action."""
        policy = self.get(policy_name)
        if policy:
            return policy.execute_action(context)
        return None

    def enable(self, name: str) -> bool:
        """Enable a policy."""
        policy = self.get(name)
        if policy:
            policy.enabled = True
            return True
        return False

    def disable(self, name: str) -> bool:
        """Disable a policy."""
        policy = self.get(name)
        if policy:
            policy.enabled = False
            return True
        return False

    def get_stats(self) -> Dict[str, Any]:
        """Get policy engine statistics."""
        return {
            "total_policies": len(self._policies),
            "enabled_policies": sum(1 for p in self._policies.values() if p.enabled),
            "evaluation_counts": self._evaluation_count.copy(),
            "trigger_counts": self._trigger_count.copy()
        }

    def export_manifest(self) -> Dict[str, Any]:
        """Export policy manifest."""
        return {
            "version": "1.0.0",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "policies": {
                name: policy.to_dict()
                for name, policy in self._policies.items()
            },
            "stats": self.get_stats()
        }

    def import_manifest(self, manifest: Dict[str, Any]) -> int:
        """Import policies from manifest."""
        count = 0
        for name, data in manifest.get("policies", {}).items():
            try:
                policy = Policy(
                    name=name,
                    condition=PolicyCondition(data["condition"]),
                    action=PolicyAction(data["action"]),
                    priority=data.get("priority", 100),
                    enabled=data.get("enabled", True),
                    max_retries=data.get("max_retries", 3),
                    parameters=data.get("parameters", {}),
                    metadata=data.get("metadata", {})
                )
                self.register(policy)
                count += 1
            except Exception as e:
                print(f"Failed to import policy {name}: {e}")

        return count


# Global policy engine
_global_engine: Optional[PolicyEngine] = None


def get_policy_engine() -> PolicyEngine:
    """Get the global policy engine."""
    global _global_engine
    if _global_engine is None:
        _global_engine = PolicyEngine()
    return _global_engine


def load_policies(manifest_path: Path) -> int:
    """Load policies from a manifest file."""
    with open(manifest_path) as f:
        manifest = json.load(f)
    return get_policy_engine().import_manifest(manifest)


def evaluate_policy(context: Dict[str, Any]) -> List[PolicyResult]:
    """Evaluate policies against a context."""
    return get_policy_engine().evaluate(context)
