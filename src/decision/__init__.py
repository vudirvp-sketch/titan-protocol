# TITAN Protocol - Decision Module
"""
Conflict Resolution Formula Engine for TITAN FUSE Protocol.

ITEM-CAT-04: Mathematical formula for idea-level conflicts.
score = accuracy×0.40 + utility×0.35 + efficiency×0.15 + consensus×0.10

Provides deterministic weighted formula and threshold-based decision logic.
"""

from .conflict_resolver import (
    ConflictMetrics,
    ConflictResolver,
    Decision as ConflictDecision,
    DecisionConfidence,
    DEFAULT_CONFLICT_WEIGHTS,
    create_conflict_resolver,
)

__all__ = [
    'ConflictMetrics',
    'ConflictResolver',
    'ConflictDecision',
    'DecisionConfidence',
    'DEFAULT_CONFLICT_WEIGHTS',
    'create_conflict_resolver',
]
