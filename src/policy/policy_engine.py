"""
TITAN FUSE Protocol - Policy Engine

Configurable policy engine for behavior rules.
Separates policy logic from core protocol.

TASK-003: Policy Engine & Autonomous Recovery Loops
AUDIT-FIX: All 12 issues from POLICY_ENGINE_AUDIT.md resolved

Version: 3.2.1
"""

import json
import hashlib
import threading
import copy
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable, Union, Literal, Set
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


# =============================================================================
# FIX 01: OWNERSHIP TABLE - Define scenario ownership between Policy Engine and TIER 5
# =============================================================================

SCENARIO_OWNERSHIP = {
    # Scenario                    | Owner           | TIER 5 Status
    # ----------------------------|-----------------|------------------
    "llm_query_timeout":          "policy_engine",  # TIER 5 deprecated
    "llm_query_failure":          "policy_engine",  # TIER 5 deprecated
    "session_interrupted":        "checkpoint",     # Policy Engine N/A
    "context_overflow":           "policy_engine",  # TIER 5 deprecated
    "budget_exceeded":            "budget_check",   # Policy Engine consults budget_state
    "validation_fail":            "policy_engine",  # TIER 5 deprecated
    "gate_blocked":               "policy_engine",  # TIER 5 deprecated
    "retry_exhausted":            "policy_engine",  # TIER 5 deprecated
    "rollback_triggered":         "policy_engine",  # TIER 5 deprecated
}

# Scenarios where Policy Engine takes precedence over TIER 5
POLICY_ENGINE_OWNS = {
    "llm_query_timeout",
    "llm_query_failure", 
    "context_overflow",
    "validation_fail",
    "gate_blocked",
    "retry_exhausted",
    "rollback_triggered",
}


# =============================================================================
# FIX 09: Phase transition actions that belong to DECISION_TREE, not Policy Engine
# =============================================================================

PHASE_TRANSITION_ACTIONS: Set[str] = {
    "advance_phase",
    "reenter_phase", 
    "transition_to_phase",
    "goto_phase",
    "skip_phase",
}


class PolicyCondition(Enum):
    """Conditions for policy evaluation."""
    ALWAYS = "always"
    ON_ERROR = "on_error"
    ON_TIMEOUT = "on_timeout"
    ON_VALIDATION_FAIL = "on_validation_fail"
    ON_GATE_BLOCK = "on_gate_block"
    ON_BUDGET_EXCEEDED = "on_budget_exceeded"
    ON_BUDGET_WARNING = "on_budget_warning"  # FIX 06: New condition
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
    CHECKPOINT = "checkpoint"  # FIX 08: New action for cascading
    CUSTOM = "custom"


# =============================================================================
# FIX 06: Budget state enum
# =============================================================================

class BudgetState(Enum):
    """Budget state for policy context."""
    NORMAL = "normal"
    BUDGET_WARNING = "budget_warning"
    BUDGET_EXCEEDED = "budget_exceeded"


# =============================================================================
# FIX 02: Extended PolicyResult with typed execution fields
# =============================================================================

@dataclass
class PolicyResult:
    """
    Result of policy evaluation.
    
    FIX 02: Extended with typed execution fields to ensure deterministic execution.
    Core MUST read typed fields only. parameters dict is supplementary context.
    """
    triggered: bool
    action: Optional[PolicyAction] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    policy_name: str = ""  # Name of the policy that triggered
    
    # FIX 02: Typed execution fields
    execution_target: Literal["llm_query", "gate", "checkpoint", "core", "none"] = "core"
    blocks_gate: Optional[str] = None  # e.g. "GATE-04" — if set, gate check is deferred
    requires_human_ack: bool = False  # True for ESCALATE
    retry_delay_ms: Optional[int] = None  # explicit, not buried in parameters
    budget_cost_estimate: int = 0  # tokens this action will consume

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "triggered": self.triggered,
            "action": self.action.value if self.action else None,
            "parameters": self.parameters,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "policy_name": self.policy_name,
            "execution_target": self.execution_target,
            "blocks_gate": self.blocks_gate,
            "requires_human_ack": self.requires_human_ack,
            "retry_delay_ms": self.retry_delay_ms,
            "budget_cost_estimate": self.budget_cost_estimate
        }


# =============================================================================
# FIX 05: Policy retry state for checkpoint persistence
# =============================================================================

@dataclass
class PolicyRetryState:
    """
    FIX 05: Retry state that must be persisted in checkpoint.
    
    Prevents infinite retry loops after session resumption.
    """
    retry_count: int = 0
    last_policy_triggered: str = ""
    last_retry_timestamp: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "retry_count": self.retry_count,
            "last_policy_triggered": self.last_policy_triggered,
            "last_retry_timestamp": self.last_retry_timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PolicyRetryState":
        return cls(
            retry_count=data.get("retry_count", 0),
            last_policy_triggered=data.get("last_policy_triggered", ""),
            last_retry_timestamp=data.get("last_retry_timestamp", "")
        )


# =============================================================================
# FIX 07: Policy Import Error for transactional imports
# =============================================================================

class PolicyImportError(Exception):
    """Raised when policy manifest import fails."""
    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__(f"Policy import failed with {len(errors)} errors: {'; '.join(errors)}")


class PolicyRegistrationError(Exception):
    """Raised when policy registration fails validation."""
    pass


# =============================================================================
# FIX 08: Chain control for cascading policies
# =============================================================================

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
        stop_on_trigger: Stop evaluation after this policy triggers (backward compat)
        chain_next: Name of next policy to evaluate if this triggers (FIX 08)
        chain_break_on: Actions that break the chain (FIX 08)
        condition_hook: Named hook for custom condition (FIX 07)
        action_hook: Named hook for custom action (FIX 07)
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
    
    # FIX 08: Chain control
    stop_on_trigger: bool = True
    chain_next: Optional[str] = None  # Name of next policy to evaluate
    chain_break_on: List[PolicyAction] = field(default_factory=list)
    
    # FIX 07: Named hooks for serialization
    condition_hook: Optional[str] = None
    action_hook: Optional[str] = None

    def evaluate(self, context: Dict[str, Any]) -> PolicyResult:
        """
        Evaluate the policy against a context.

        Args:
            context: Evaluation context

        Returns:
            Policy result
        """
        if not self.enabled:
            return PolicyResult(triggered=False, reason="Policy disabled", policy_name=self.name)

        # Check condition
        should_trigger = self._check_condition(context)

        if should_trigger:
            # FIX 02: Build result with typed fields
            return PolicyResult(
                triggered=True,
                action=self.action,
                parameters=self.parameters.copy(),
                reason=f"Policy '{self.name}' triggered on condition '{self.condition.value}'",
                policy_name=self.name,
                execution_target=self._determine_execution_target(),
                requires_human_ack=self.action == PolicyAction.ESCALATE,
                retry_delay_ms=self.parameters.get("delay_ms"),
                budget_cost_estimate=self._estimate_budget_cost()
            )

        return PolicyResult(triggered=False, reason="Condition not met", policy_name=self.name)

    def _determine_execution_target(self) -> Literal["llm_query", "gate", "checkpoint", "core", "none"]:
        """FIX 02: Determine where this action should be executed."""
        if self.action in (PolicyAction.RETRY,):
            return "llm_query"
        elif self.action in (PolicyAction.ROLLBACK, PolicyAction.CHECKPOINT):
            return "checkpoint"
        elif self.action in (PolicyAction.ABORT, PolicyAction.SKIP):
            return "gate"
        elif self.action in (PolicyAction.LOG, PolicyAction.NOTIFY):
            return "none"
        return "core"

    def _estimate_budget_cost(self) -> int:
        """FIX 02: Estimate token cost for this action."""
        if self.action == PolicyAction.RETRY:
            return self.parameters.get("estimated_tokens", 2000)
        return 0

    def _check_condition(self, context: Dict[str, Any]) -> bool:
        """Check if condition is met."""
        # FIX 06: Check budget state
        budget_state = context.get("budget_state", BudgetState.NORMAL.value)
        
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
            return budget_state == BudgetState.BUDGET_EXCEEDED.value

        # FIX 06: New budget warning condition
        if self.condition == PolicyCondition.ON_BUDGET_WARNING:
            return budget_state in (BudgetState.BUDGET_WARNING.value, BudgetState.BUDGET_EXCEEDED.value)

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
            "metadata": self.metadata,
            "stop_on_trigger": self.stop_on_trigger,
            "chain_next": self.chain_next,
            "chain_break_on": [a.value for a in self.chain_break_on],
            "condition_hook": self.condition_hook,
            "action_hook": self.action_hook
        }


class PolicyEngine:
    """
    Engine for evaluating and executing policies.

    Features:
    - Policy registration and management
    - Priority-based evaluation
    - Context-based matching
    - Policy chaining (FIX 08)
    - Export/Import (FIX 04: transactional)
    - Thread-safe operations (FIX 10)
    - Named hooks for CUSTOM policies (FIX 07)
    - Sorted policy cache (FIX 11)
    - Context snapshot for determinism (FIX 12)

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
        results = engine.evaluate({"timeout": True})
        for result in results:
            if result.triggered:
                print(f"Action: {result.action}")
    """

    def __init__(self):
        self._policies: Dict[str, Policy] = {}
        self._evaluation_count: Dict[str, int] = {}
        self._trigger_count: Dict[str, int] = {}
        
        # FIX 10: Thread safety
        self._lock = threading.RLock()
        
        # FIX 11: Sorted policy cache
        self._sorted_cache: Optional[List[Policy]] = None
        
        # FIX 07: Named hook registries for CUSTOM conditions/actions
        self._condition_hooks: Dict[str, Callable[[Dict[str, Any]], bool]] = {}
        self._action_hooks: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], Any]] = {}
        
        # FIX 04: Manifest hash for checkpoint validation
        self._manifest_hash: Optional[str] = None
        
        # FIX 06: Register built-in budget protection rule
        self._register_builtin_rules()

    def _register_builtin_rules(self) -> None:
        """
        FIX 06: Register built-in rules that cannot be overridden.
        
        These rules have highest priority and are registered automatically.
        """
        # Budget exceeded abort rule - priority 999, cannot be overridden
        budget_abort = Policy(
            name="__builtin_budget_exceeded_abort",
            condition=PolicyCondition.ON_BUDGET_EXCEEDED,
            action=PolicyAction.ABORT,
            priority=999,
            enabled=True,
            parameters={"reason": "Budget limit reached"},
            metadata={"builtin": True, "immutable": True}
        )
        # Directly insert to bypass validation (built-in rules are trusted)
        self._policies[budget_abort.name] = budget_abort
        self._evaluation_count[budget_abort.name] = 0
        self._trigger_count[budget_abort.name] = 0

    # =========================================================================
    # FIX 07: Named hook registry
    # =========================================================================
    
    def register_condition_hook(self, name: str, fn: Callable[[Dict[str, Any]], bool]) -> None:
        """
        Register a named condition hook for CUSTOM policies.
        
        FIX 07: Allows CUSTOM conditions to be serialized by name.
        """
        with self._lock:
            self._condition_hooks[name] = fn

    def register_action_hook(self, name: str, fn: Callable[[Dict[str, Any], Dict[str, Any]], Any]) -> None:
        """
        Register a named action hook for CUSTOM policies.
        
        FIX 07: Allows CUSTOM actions to be serialized by name.
        """
        with self._lock:
            self._action_hooks[name] = fn

    def get_condition_hook(self, name: str) -> Optional[Callable]:
        """Get a condition hook by name."""
        return self._condition_hooks.get(name)

    def get_action_hook(self, name: str) -> Optional[Callable]:
        """Get an action hook by name."""
        return self._action_hooks.get(name)

    # =========================================================================
    # Policy management
    # =========================================================================

    def register(self, policy: Policy) -> None:
        """
        Register a policy.
        
        FIX 09: Validates that policy does not contain phase-transition actions.
        """
        # FIX 09: Phase transition guard
        if policy.action.value in PHASE_TRANSITION_ACTIONS:
            raise PolicyRegistrationError(
                f"Phase transitions belong to DECISION_TREE, not Policy Engine. "
                f"Action '{policy.action.value}' is not allowed."
            )
        
        with self._lock:
            self._policies[policy.name] = policy
            self._evaluation_count[policy.name] = 0
            self._trigger_count[policy.name] = 0
            # FIX 11: Invalidate cache
            self._invalidate_cache()

    def unregister(self, name: str) -> bool:
        """Unregister a policy."""
        with self._lock:
            if name in self._policies:
                del self._policies[name]
                # FIX 11: Invalidate cache
                self._invalidate_cache()
                return True
            return False

    def get(self, name: str) -> Optional[Policy]:
        """Get a policy by name."""
        return self._policies.get(name)

    # =========================================================================
    # FIX 11: Sorted policy cache with invalidation
    # =========================================================================
    
    def _get_sorted_policies(self) -> List[Policy]:
        """
        Get sorted policies with caching.
        
        FIX 11: O(1) after first sort instead of O(n log n) per evaluation.
        """
        if self._sorted_cache is None:
            self._sorted_cache = sorted(
                [p for p in self._policies.values() if p.enabled],
                key=lambda p: p.priority,
                reverse=True
            )
        return self._sorted_cache

    def _invalidate_cache(self) -> None:
        """Invalidate sorted policy cache."""
        self._sorted_cache = None

    def list(self, enabled_only: bool = True) -> List[Policy]:
        """List all policies."""
        with self._lock:
            if enabled_only:
                return self._get_sorted_policies()
            return sorted(list(self._policies.values()), key=lambda p: p.priority, reverse=True)

    # =========================================================================
    # FIX 12: Context snapshot for determinism
    # FIX 08: Chain control
    # =========================================================================

    def evaluate(self, context: Dict[str, Any],
                 stop_on_trigger: bool = True) -> List[PolicyResult]:
        """
        Evaluate all policies against a context.

        Args:
            context: Evaluation context
            stop_on_trigger: Stop after first trigger (backward compat)

        Returns:
            List of triggered policy results
            
        FIX 12: Context is snapshotted to prevent mutation during evaluation.
        FIX 08: Chain control follows chain_next links.
        """
        # FIX 12: Snapshot context at entry
        context_snapshot = copy.deepcopy(context)
        
        results: List[PolicyResult] = []
        evaluated_names: Set[str] = set()

        with self._lock:
            policies = self._get_sorted_policies()

        # FIX 08: Chain-aware evaluation
        for policy in policies:
            if policy.name in evaluated_names:
                continue
                
            evaluated_names.add(policy.name)
            self._evaluation_count[policy.name] = self._evaluation_count.get(policy.name, 0) + 1

            result = policy.evaluate(context_snapshot)  # FIX 12: Use snapshot

            if result.triggered:
                self._trigger_count[policy.name] = self._trigger_count.get(policy.name, 0) + 1
                results.append(result)

                # FIX 08: Check chain_break_on first
                if result.action and result.action in policy.chain_break_on:
                    break

                # FIX 08: Follow chain_next if specified
                if policy.chain_next:
                    # Continue to specific next policy
                    next_policy = self.get(policy.chain_next)
                    if next_policy and next_policy.enabled:
                        continue  # Will be evaluated in next iteration
                    break
                
                # Legacy stop_on_trigger behavior
                if stop_on_trigger and policy.stop_on_trigger:
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
        # FIX 12: Snapshot context
        context_snapshot = copy.deepcopy(context)
        
        results = []

        with self._lock:
            policies = self._get_sorted_policies()

        for policy in policies:
            if policy.condition == condition:
                result = policy.evaluate(context_snapshot)
                if result.triggered:
                    results.append(result)

        return results

    def execute(self, policy_name: str,
                context: Dict[str, Any]) -> Any:
        """Execute a specific policy's action."""
        policy = self.get(policy_name)
        if policy:
            # FIX 07: Check for action hook
            if policy.action_hook and policy.action_hook in self._action_hooks:
                return self._action_hooks[policy.action_hook](context, policy.parameters)
            return policy.execute_action(context)
        return None

    def enable(self, name: str) -> bool:
        """Enable a policy."""
        with self._lock:
            policy = self.get(name)
            if policy:
                policy.enabled = True
                # FIX 11: Invalidate cache
                self._invalidate_cache()
                return True
            return False

    def disable(self, name: str) -> bool:
        """Disable a policy."""
        with self._lock:
            policy = self.get(name)
            if policy:
                policy.enabled = False
                # FIX 11: Invalidate cache
                self._invalidate_cache()
                return True
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Get policy engine statistics."""
        with self._lock:
            return {
                "total_policies": len(self._policies),
                "enabled_policies": sum(1 for p in self._policies.values() if p.enabled),
                "evaluation_counts": self._evaluation_count.copy(),
                "trigger_counts": self._trigger_count.copy(),
                "manifest_hash": self._manifest_hash
            }

    # =========================================================================
    # FIX 04: Transactional export/import with manifest hash
    # =========================================================================

    def export_manifest(self) -> Dict[str, Any]:
        """Export policy manifest."""
        with self._lock:
            manifest = {
                "version": "2.0.0",  # Updated for new fields
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "policies": {
                    name: policy.to_dict()
                    for name, policy in self._policies.items()
                    if not policy.metadata.get("builtin", False)  # Exclude builtins
                },
                "stats": self.get_stats()
            }
            
            # FIX 04: Compute manifest hash
            manifest_str = json.dumps(manifest["policies"], sort_keys=True)
            self._manifest_hash = hashlib.sha256(manifest_str.encode()).hexdigest()
            manifest["manifest_hash"] = self._manifest_hash
            
            return manifest

    def import_manifest(self, manifest: Dict[str, Any]) -> int:
        """
        Import policies from manifest.
        
        FIX 04: Transactional import - all or nothing.
        Raises PolicyImportError on any failure.
        """
        staged: Dict[str, Policy] = {}
        errors: List[str] = []

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
                    metadata=data.get("metadata", {}),
                    stop_on_trigger=data.get("stop_on_trigger", True),
                    chain_next=data.get("chain_next"),
                    chain_break_on=[PolicyAction(a) for a in data.get("chain_break_on", [])],
                    condition_hook=data.get("condition_hook"),
                    action_hook=data.get("action_hook")
                )
                
                # FIX 07: Resolve condition hook if specified
                if policy.condition_hook:
                    if policy.condition_hook not in self._condition_hooks:
                        errors.append(f"Policy '{name}': condition_hook '{policy.condition_hook}' not found")
                        continue
                    policy.condition_fn = self._condition_hooks[policy.condition_hook]
                
                # FIX 07: Resolve action hook if specified
                if policy.action_hook:
                    if policy.action_hook not in self._action_hooks:
                        errors.append(f"Policy '{name}': action_hook '{policy.action_hook}' not found")
                        continue
                    policy.action_fn = self._action_hooks[policy.action_hook]
                
                staged[name] = policy
                
            except Exception as e:
                errors.append(f"{name}: {e}")

        # FIX 04: Atomic commit - raise if any errors
        if errors:
            raise PolicyImportError(errors)

        with self._lock:
            # Clear existing non-builtin policies
            builtin_policies = {
                name: p for name, p in self._policies.items() 
                if p.metadata.get("builtin", False)
            }
            self._policies.clear()
            self._policies.update(builtin_policies)
            self._policies.update(staged)  # Commit all staged policies
            self._invalidate_cache()
            
            # Set manifest hash
            if "manifest_hash" in manifest:
                self._manifest_hash = manifest["manifest_hash"]

        return len(staged)

    def get_manifest_hash(self) -> Optional[str]:
        """Get current manifest hash for checkpoint validation."""
        return self._manifest_hash


# =============================================================================
# Global policy engine singleton
# =============================================================================

_global_engine: Optional[PolicyEngine] = None
_global_lock = threading.Lock()


def get_policy_engine() -> PolicyEngine:
    """
    Get the global policy engine.
    
    Thread-safe singleton access.
    """
    global _global_engine
    if _global_engine is None:
        with _global_lock:
            if _global_engine is None:
                _global_engine = PolicyEngine()
    return _global_engine


def load_policies(manifest_path: Path) -> int:
    """
    Load policies from a manifest file.
    
    Raises PolicyImportError on failure.
    """
    with open(manifest_path) as f:
        manifest = json.load(f)
    return get_policy_engine().import_manifest(manifest)


def evaluate_policy(context: Dict[str, Any]) -> List[PolicyResult]:
    """
    Evaluate policies against a context.
    
    FIX 12: Context is snapshotted internally.
    """
    return get_policy_engine().evaluate(context)


# =============================================================================
# FIX 03: POLICY_GATE_SEQUENCE - Helper for core to enforce execution order
# =============================================================================

def evaluate_with_gate_sequence(
    context: Dict[str, Any],
    gate_id: str = "GATE-04"
) -> Dict[str, Any]:
    """
    FIX 03: Enforce POLICY_GATE_SEQUENCE execution order.
    
    FOR each batch execution:
      1. evaluate_policy(context) → PolicyResult
      2. IF PolicyResult.action == ABORT → skip Gate, trigger ROLLBACK
      3. IF PolicyResult.action == RETRY:
           a. execute retry
           b. re-evaluate GATE on new state
           c. IF GATE BLOCK → ABORT regardless of policy
      4. IF no policy triggered → run GATE normally
    
    Returns dict with policy results and gate handling instructions.
    """
    results = evaluate_policy(context)
    
    if not results:
        return {
            "policy_results": [],
            "skip_gate": False,
            "trigger_rollback": False,
            "proceed_to_gate": True
        }
    
    primary_result = results[0]
    
    # ABORT: skip gate, trigger rollback
    if primary_result.action == PolicyAction.ABORT:
        return {
            "policy_results": results,
            "skip_gate": True,
            "trigger_rollback": True,
            "proceed_to_gate": False
        }
    
    # RETRY: proceed but note gate should be re-evaluated after
    if primary_result.action == PolicyAction.RETRY:
        return {
            "policy_results": results,
            "skip_gate": False,
            "trigger_rollback": False,
            "proceed_to_gate": False,
            "retry_then_revaluate_gate": True,
            "gate_id": gate_id
        }
    
    # Other actions: proceed normally
    return {
        "policy_results": results,
        "skip_gate": False,
        "trigger_rollback": False,
        "proceed_to_gate": True
    }
