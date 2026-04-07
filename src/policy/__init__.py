# TITAN FUSE Protocol - Policy Module
"""
Policy routing, intent classification, and gate evaluation.

ITEM-ARCH-04: Gate-04 SEV-1 Override Fix
ITEM-GATE-01: Gate-04 Early Exit Fix
ITEM-GATE-02: Mode-Based Gate Sensitivity
ITEM-POLICY-01: PolicyResolver for EQUIP Stage
"""

from .intent_router import IntentRouter, IntentResult, INTENT_CHAINS
from .policy_engine import (
    PolicyEngine, Policy, PolicyResult, PolicyCondition, PolicyAction,
    get_policy_engine, evaluate_policy, evaluate_with_gate_sequence
)
from .gate_evaluation import (
    Gate04Evaluator, Gate04Result, GateResult, Severity, Gap,
    evaluate_gate_04, check_gate_04_early_exit
)
from .gate_behavior import (
    GateBehaviorModifier, GateSensitivityConfig, ExecutionMode,
    ModifiedGateResult, get_gate_behavior_modifier, apply_gate_mode_rules
)
from .policy_resolver import (
    PolicyResolver, ConflictType, Conflict, ResolutionStatus,
    ResolutionResult, Skill, Constraints, Constraint, ToolConstraint,
    BudgetConstraint, create_policy_resolver, resolve_skill_policy,
    lint_skills
)

__all__ = [
    # Intent routing
    'IntentRouter', 
    'IntentResult', 
    'INTENT_CHAINS',
    
    # Policy engine
    'PolicyEngine',
    'Policy',
    'PolicyResult',
    'PolicyCondition',
    'PolicyAction',
    'get_policy_engine',
    'evaluate_policy',
    'evaluate_with_gate_sequence',
    
    # Gate evaluation (ITEM-ARCH-04, ITEM-GATE-01)
    'Gate04Evaluator',
    'Gate04Result',
    'GateResult',
    'Severity',
    'Gap',
    'evaluate_gate_04',
    'check_gate_04_early_exit',
    
    # Gate behavior (ITEM-GATE-02)
    'GateBehaviorModifier',
    'GateSensitivityConfig',
    'ExecutionMode',
    'ModifiedGateResult',
    'get_gate_behavior_modifier',
    'apply_gate_mode_rules',
    
    # Policy resolver (ITEM-POLICY-01)
    'PolicyResolver',
    'ConflictType',
    'Conflict',
    'ResolutionStatus',
    'ResolutionResult',
    'Skill',
    'Constraints',
    'Constraint',
    'ToolConstraint',
    'BudgetConstraint',
    'create_policy_resolver',
    'resolve_skill_policy',
    'lint_skills',
]
