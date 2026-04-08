# TITAN FUSE Protocol - State Module
"""State management, assessment, and cursor tracking."""

from .assessment import AssessmentScore, SignalStrength, ReadinessTier
from .state_manager import SessionState, ReasoningStep, EvidenceType, BudgetManager, BudgetAllocation
from .cursor import (
    CursorTracker,
    CursorState,
    DriftResult,
    compute_state_hash,
    verify_state_integrity
)
from .checkpoint_serialization import (
    SerializationFormat,
    SerializationResult,
    serialize_checkpoint,
    deserialize_checkpoint,
    serialize_checkpoint_to_storage,
    deserialize_checkpoint_from_storage,
    add_cursor_hash_to_checkpoint,
    verify_checkpoint_cursor_hash,
    deserialize_checkpoint_with_verification
)
from .checkpoint_manager import (
    CheckpointManager,
    CheckpointMetadata,
    get_checkpoint_manager
)
# ITEM-ARCH-16: External State Drift Policy
from .drift_policy import (
    ConflictPolicy,
    DriftReport,
    DriftPolicyHandler,
    DriftDetectedError,
    MergeConflictError,
    ActionResult,
    check_state_drift
)
# ITEM-FEAT-72: Checkpoint Compression with Deduplication
from .checkpoint_compression import (
    CheckpointCompressor,
    CompressionStats,
    CompressionAlgorithm,
    compress_checkpoint,
    decompress_checkpoint,
    estimate_compression
)

__all__ = [
    'AssessmentScore',
    'SignalStrength',
    'ReadinessTier',
    'SessionState',
    'ReasoningStep',
    'EvidenceType',
    'BudgetManager',
    'BudgetAllocation',
    # ITEM-STOR-05: Cursor tracking
    'CursorTracker',
    'CursorState',
    'DriftResult',
    'compute_state_hash',
    'verify_state_integrity',
    # ITEM-SEC-02: Checkpoint serialization
    'SerializationFormat',
    'SerializationResult',
    'serialize_checkpoint',
    'deserialize_checkpoint',
    'serialize_checkpoint_to_storage',
    'deserialize_checkpoint_from_storage',
    # ITEM-STOR-05: Cursor hash for checkpoint
    'add_cursor_hash_to_checkpoint',
    'verify_checkpoint_cursor_hash',
    'deserialize_checkpoint_with_verification',
    # ITEM-STOR-02: Checkpoint manager
    'CheckpointManager',
    'CheckpointMetadata',
    'get_checkpoint_manager',
    # ITEM-ARCH-16: External State Drift Policy
    'ConflictPolicy',
    'DriftReport',
    'DriftPolicyHandler',
    'DriftDetectedError',
    'MergeConflictError',
    'ActionResult',
    'check_state_drift',
    # ITEM-FEAT-72: Checkpoint Compression with Deduplication
    'CheckpointCompressor',
    'CompressionStats',
    'CompressionAlgorithm',
    'compress_checkpoint',
    'decompress_checkpoint',
    'estimate_compression'
]
