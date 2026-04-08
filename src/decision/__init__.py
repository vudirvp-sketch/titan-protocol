# TITAN Protocol - Decision Module
"""
Conflict Resolution Formula Engine for TITAN FUSE Protocol.

ITEM-CAT-04: Mathematical formula for idea-level conflicts.
score = accuracy×0.40 + utility×0.35 + efficiency×0.15 + consensus×0.10

ITEM-ART-002: Decision Record Enforcement for ARTIFACT_CONTRACT compliance.

Provides deterministic weighted formula and threshold-based decision logic.
Also provides DecisionRecordManager for enforcing DECISION_RECORD artifact.
"""

from .conflict_resolver import (
    ConflictMetrics,
    ConflictResolver,
    Decision as ConflictDecision,
    DecisionConfidence,
    DEFAULT_CONFLICT_WEIGHTS,
    create_conflict_resolver,
)

from .decision_record import (
    DecisionType,
    Decision,
    DecisionRecordArtifact,
    DecisionRecordManager,
    create_decision_record_manager,
    write_decision_record,
)

__all__ = [
    # Conflict Resolution (ITEM-CAT-04)
    'ConflictMetrics',
    'ConflictResolver',
    'ConflictDecision',
    'DecisionConfidence',
    'DEFAULT_CONFLICT_WEIGHTS',
    'create_conflict_resolver',
    # Decision Record (ITEM-ART-002)
    'DecisionType',
    'Decision',
    'DecisionRecordArtifact',
    'DecisionRecordManager',
    'create_decision_record_manager',
    'write_decision_record',
]
