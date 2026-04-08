# TITAN FUSE Protocol - Planning Module
"""Planning and state snapshot management.

ITEM-DAG-112: Enhanced cycle detection with DAG and Amendment support.
"""

from .state_snapshot import StateSnapshot, SnapshotManager
from .cycle_detector import (
    CycleDetector,
    DAG,
    DAGNode,
    Amendment,
    AmendmentType,
    validate_dag,
    validate_dag_object
)
from .planning_engine import (
    PlanningEngine,
    EngineState,
    HaltReason,
    PlanStep,
    ValidationResult
)

__all__ = [
    # State management
    'StateSnapshot',
    'SnapshotManager',
    
    # ITEM-DAG-112: Cycle detection
    'CycleDetector',
    'DAG',
    'DAGNode',
    'Amendment',
    'AmendmentType',
    'validate_dag',
    'validate_dag_object',
    
    # ITEM-DAG-112: Planning engine
    'PlanningEngine',
    'EngineState',
    'HaltReason',
    'PlanStep',
    'ValidationResult'
]
