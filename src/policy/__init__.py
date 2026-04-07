# TITAN FUSE Protocol - Policy Module
"""
Policy routing, intent classification, and gate evaluation.

ITEM-ARCH-04: Gate-04 SEV-1 Override Fix
ITEM-GATE-01: Gate-04 Early Exit Fix
ITEM-GATE-02: Mode-Based Gate Sensitivity
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
    'apply_gate_mode_rules'
]
