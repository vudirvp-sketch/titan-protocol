# TITAN Protocol - Agents Module
"""
SCOUT Roles Matrix Agent Framework for TITAN FUSE Protocol.

ITEM-CAT-02: Four specialized agents with explicit roles:
- RADAR: Domain/signal classification
- DEVIL: Hype detection and risk flagging
- EVAL: Readiness assessment with veto power
- STRAT: Strategy synthesis respecting EVAL constraints

Enforces mandatory DEVIL→EVAL→STRAT pipeline with veto propagation.
"""

from .scout_matrix import (
    AgentRole,
    AgentBase,
    RADARAgent,
    DEVILAgent,
    EVALAgent,
    STRATAgent,
    ScoutPipeline,
    AnalysisContext,
    AdoptionReadiness,
    ScoutOutput,
    create_scout_pipeline,
)

__all__ = [
    'AgentRole',
    'AgentBase',
    'RADARAgent',
    'DEVILAgent',
    'EVALAgent',
    'STRATAgent',
    'ScoutPipeline',
    'AnalysisContext',
    'AdoptionReadiness',
    'ScoutOutput',
    'create_scout_pipeline',
]
